# Controle de rotor: gpredict → GRS Manager → Station Manager → Rotor Manager

Guia de arquitetura, setup e teste do pipeline completo de apontamento de
antena — desde o **Satellite Tracker** (gpredict) até o **Rotor Controller**
físico (AlfaSpid Rot2Prog).

## Arquitetura

O pipeline segue a simetria do diagrama oficial da arquitetura GRS: cada
"Manager" é um adapter entre um protocolo de terceiros e o vizinho seguinte.

```
Satellite Tracker  --rotctld (TCP)-->  GRS Manager  --ZMQ REQ/REP-->  Station Manager  --ZMQ PUSH/PULL+PUB/SUB-->  Rotor Manager  --Rot2Prog (serial)-->  Rotor Controller
   (gpredict)          protocolo           src/                        src/mgm8/           protocolo do              vendor/                (binário)         (hardware ou
                        hamlib          grs_manager/                                        grs-rotor-manager      grs-rotor-manager                        rotor_simulator.py)
```

| Componente | Papel | Código |
|---|---|---|
| **Satellite Tracker** | Cliente rotctld, não é nosso | gpredict |
| **GRS Manager** | Adapter: fala rotctld pro gpredict, fala ZMQ pro Station Manager | [`src/grs_manager/`](../src/grs_manager/) |
| **Station Manager** | Núcleo de negócio (clamp de curso) + adapter de saída pro Rotor Manager | [`src/mgm8/`](../src/mgm8/) |
| **Rotor Manager** | Adapter: fala ZMQ pro Station Manager, fala Rot2Prog binário pro rotor | [`vendor/grs-rotor-manager/`](../vendor/grs-rotor-manager/) (submódulo git) |
| **Rotor Controller** | Hardware físico (AlfaSpid) | — no teste, `rotor_simulator.py` faz esse papel |

Cada seta do diagrama é um **protocolo diferente**, e cada "Manager" só
conhece os dois vizinhos imediatos — nenhum deles importa código do outro
lado da rede. GRS Manager e Station Manager, em especial, são processos
independentes que só se falam por ZMQ; por isso têm cada um seu próprio
value object de posição (`grs_manager.domain.models.RotorPosition` e
`mgm8.domain.models.AntennaPosition`), mesmo sendo estruturalmente iguais.

### GRS Manager (`src/grs_manager/`)

- **Adapter de entrada** — [`rotctld/server.py`](../src/grs_manager/rotctld/server.py): servidor TCP, implementa o subconjunto do protocolo rotctld que o gpredict usa (`p`, `P`, `S`, `\dump_state`, `q`). Também rastreia quantas conexões TCP estão abertas (`is_gpredict_connected`), usado pelo painel de status.
- **Adapter de saída** — [`adapters/station_manager_zmq.py`](../src/grs_manager/adapters/station_manager_zmq.py): cliente ZMQ REQ, fala com o Station Manager num protocolo JSON próprio (schema documentado no topo do arquivo).
- **Painel de status** — [`status/app.py`](../src/grs_manager/status/app.py): app Flask que mostra se o gpredict está conectado e se o rotor está respondendo (ver seção própria abaixo).
- **Composition root** — [`main.py`](../src/grs_manager/main.py).

### Station Manager (`src/mgm8/`)

- **Adapter de entrada (rotor)** — [`rotor_zmq/server.py`](../src/mgm8/rotor_zmq/server.py): servidor ZMQ REP, espelha o schema JSON do GRS Manager.
- **Núcleo** — [`application/tracking_service.py`](../src/mgm8/application/tracking_service.py): faz o clamp de curso (limites de az/el) e loga o valor real (decimal, sem arredondar) antes de repassar ao rotor.
- **Adapters de saída (rotor)** — [`infrastructure/mock_rotor.py`](../src/mgm8/infrastructure/mock_rotor.py) (fake em memória) e [`infrastructure/rot2prog_zmq.py`](../src/mgm8/infrastructure/rot2prog_zmq.py) (envolve o `RotorManager` do submódulo).
- **Composition root (rotor)** — [`rotor_zmq/main.py`](../src/mgm8/rotor_zmq/main.py).
- **Adapter de entrada (HTTP, não relacionado a rotor)** — `api/app.py`, para agendamento de passagens. Processo separado.

## Como testar (checklist completo)

Do mais rápido ao mais completo — cada nível só faz sentido rodar depois do
anterior passar. Esse é o roteiro usado pra validar a arquitetura
GRS Manager / Station Manager separada (ver seções detalhadas mais abaixo
pra cada passo).

### 1. Testes automatizados (segundos, sem processos externos)

```powershell
pytest
```

31 testes: protocolo rotctld do GRS Manager, dispatch ZMQ do Station
Manager, clamp de curso, painel de status, e um teste de integração com os
dois serviços conversando por ZMQ de verdade (`tests/test_rotor_pipeline_integration.py`).
Se algum falhar, não vale a pena seguir pros passos manuais.

### 2. Smoke test local (rotor mock, uma máquina só)

Confirma que os `main.py` sobem e se falam de verdade fora do pytest — veja
"Teste rápido" abaixo. Validação: `rotctl -m 2 -r 127.0.0.1:4533` responde
sem "Protocol error", ou `http://127.0.0.1:5590` mostra "rotor: ativo".

### 3. Teste completo (rotor real via ZMQ + simulador do Rotor Manager)

Mesma coisa, mas com `rotor_simulator.py` no lugar do hardware e
`--rotor zmq` no Station Manager — veja "Teste completo" abaixo. Isso
exercita a cadeia inteira: GRS Manager → Station Manager → Rotor Manager →
rotor. Validação: mandar `P <az> <el>` via `rotctl` e ver
`[Simulator] SET POSITION -> ...` aparecer no terminal do simulador.

### 4. Validação com o gpredict real, em outra máquina (o teste completo)

Os mesmos três processos do passo 3, mas com o GRS Manager escutando no IP
da rede local (`--host <IP> --status-host <IP>`) — veja "Testar com o
gpredict numa máquina separada" e "Configurando o gpredict" abaixo.

Critérios de sucesso, nessa ordem:
1. `rotctl -m 2 -r <IP>:4533` (rodando na própria máquina do gpredict)
   conecta sem "Protocol error" — confirma que o handshake `\dump_state`
   está OK e a rede está liberada, antes de mexer no gpredict.
2. No gpredict: **Engage** conecta (o painel de status em
   `http://<IP>:5590` deve virar `gpredict_connected: true` assim que
   clicar).
3. Mover manualmente (setinhas do spinner) ou ativar **Track** com um
   satélite acima do horizonte faz `gpredict_last_target` e `rotor_position`
   no painel de status mudarem juntos, com os mesmos valores (a pequena
   defasagem de 1 grau é esperada — ver "Precisão de 1 grau" nos Gotchas).
4. O terminal do `rotor_simulator.py` mostra `SET POSITION` mudando em
   tempo real acompanhando o gpredict.

Esse foi o roteiro usado pra validar a reestruturação GRS Manager / Station
Manager (antes disso, tudo vivia junto em `mgm8.rotctld`).

## Protocolos envolvidos

| Ligação | Protocolo | Quem define o formato |
|---|---|---|
| Satellite Tracker ↔ GRS Manager | rotctld (hamlib) | Terceiros (projeto hamlib) — não pode mudar |
| GRS Manager ↔ Station Manager | ZMQ REQ/REP, JSON | Nosso — pode evoluir livremente (ver docstrings de `station_manager_zmq.py` e `rotor_zmq/server.py`) |
| Station Manager ↔ Rotor Manager | ZMQ PUSH/PULL + PUB/SUB, binário Rot2Prog | `grs-rotor-manager` — protocolo do fabricante do hardware, não pode mudar |

## Pré-requisitos

```powershell
git submodule update --init --recursive   # baixa vendor/grs-rotor-manager
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,zmq]"
```

O extra `zmq` (pyzmq) é necessário nos dois serviços — tanto o GRS Manager
quanto a porta de entrada ZMQ do Station Manager (`mgm8.rotor_zmq`) dependem
dele, mesmo usando o rotor mock (só a implementação `--rotor zmq`, que fala
com o Rotor Manager real, é que é opcional).

## Teste rápido (rotor mock, sem hardware nem submódulo)

Três terminais:

```powershell
# Terminal 1 — Station Manager (núcleo + rotor mock)
python -m mgm8.rotor_zmq.main --rotor mock

# Terminal 2 — GRS Manager (aponta pro Station Manager acima)
python -m grs_manager.main

# Terminal 3 (opcional) — espiar comandos crus do gpredict/rotctl
python tools\rotctld_spy.py
```

Aponte o gpredict (ou o `rotctl`, ver abaixo) pro **GRS Manager**
(`127.0.0.1:4533`) — nunca direto no Station Manager, que não fala mais
rotctld.

## Teste completo (rotor via ZMQ + simulador do Rotor Manager)

Quatro terminais:

```powershell
# Terminal 1 — simulador do rotor (finge ser o Rotor Controller físico)
python -u vendor\grs-rotor-manager\rotor_simulator.py

# Terminal 2 — Station Manager, agora com --rotor zmq
python -m mgm8.rotor_zmq.main --rotor zmq --rotor-address tcp://127.0.0.1:5559

# Terminal 3 — GRS Manager
python -m grs_manager.main

# Terminal 4 — gpredict ou rotctl, apontando pro GRS Manager (127.0.0.1:4533)
```

Portas padrão usadas nesse pipeline:

| Porta | Serviço | Papel |
|---|---|---|
| `4533` | GRS Manager | rotctld (gpredict conecta aqui) |
| `5580` | Station Manager | ZMQ REP (GRS Manager conecta aqui) |
| `5559` | Rotor Manager | ZMQ PUSH/PULL de comandos (Station Manager conecta aqui) |
| `5560` | Rotor Manager | ZMQ PUB/SUB de status (fixo, não configurável) |

## Testar com o gpredict numa máquina separada

Se o gpredict roda numa máquina diferente da que sobe o GRS Manager, é o
**GRS Manager** que precisa escutar no IP da rede local (o Station Manager
pode continuar em `127.0.0.1`, já que só o GRS Manager fala com ele):

```powershell
python -m grs_manager.main --host <IP_DESTA_MAQUINA> --port 4533
```

Checklist se a conexão não chegar: firewall do Windows liberando `python.exe`
na porta usada, teste de conectividade a partir da máquina do gpredict
(`Test-NetConnection -ComputerName <IP> -Port 4533`), e confirmar que as duas
máquinas estão na mesma sub-rede.

## Configurando o gpredict

No painel de configuração do rotor (**Edit → Preferences → Interfaces →
Rotators → Add New**):

| Campo | Valor |
|---|---|
| Host | IP da máquina rodando o **GRS Manager** |
| Port | `4533` |
| Az type | `0° → 180° → 360°` |
| Min/Max Az | `0` / `360` |
| Min/Max El | `0` / `90` |
| **Cycle** | **≥ 20ms** — o padrão de 10ms sobrecarrega o Rotor Manager e a conexão fica instável (ver "Gotchas") |

Depois, no módulo **Antenna Control**: **Engage**, selecione um satélite em
**Target** e **Track** pra rastreio automático (só move se o satélite estiver
acima do horizonte pra localização configurada no gpredict).

## Painel de status

O GRS Manager sobe, na mesma chamada de `main.py`, um painel HTTP (Flask,
numa thread separada) em `http://127.0.0.1:5590` por padrão
(`--status-host`/`--status-port` pra mudar, `--no-status` pra desligar):

- **`GET /`** — página HTML (auto-atualiza a cada 5s) com dois indicadores: gpredict conectado (+ último alvo pedido) e rotor respondendo (+ posição atual).
- **`GET /health`** — mesmo dado em JSON:
  ```json
  {
    "gpredict_connected": true,
    "gpredict_last_target": {"azimuth_degrees": 87.3, "elevation_degrees": 15.9},
    "rotor_connected": true,
    "rotor_position": {"azimuth_degrees": 87.3, "elevation_degrees": 15.9}
  }
  ```

O indicador de gpredict reflete diretamente se há uma conexão TCP aberta no
servidor rotctld do próprio GRS Manager; `gpredict_last_target` é o último
`P <az> <el>` recebido (fica `null` até o primeiro comando, e continua
mostrando o último valor mesmo depois da conexão fechar — é histórico, não
"ao vivo"). O indicador de rotor faz uma chamada `get_position()` ao Station
Manager — só fica "ativo" se a cadeia inteira (GRS Manager → Station Manager
→ Rotor Manager → rotor) responder, e `rotor_position` traz o valor
retornado; qualquer falha em qualquer ponto (Station Manager fora do ar,
Rotor Manager sem resposta) aparece como "inativo" com `rotor_position: null`.

Esse indicador usa um `StationManagerZmqClient` **dedicado**, separado do
que atende o gpredict de verdade — um socket ZMQ REQ não é seguro pra uso
concorrente por várias threads, e um timeout na checagem de saúde deixaria o
socket "de produção" num estado inconsistente se fosse o mesmo (ver
docstring de `station_manager_zmq.py`).

## Verificando sem o gpredict

O gpredict tem bugs conhecidos e específicos de versão/plataforma no
controle de rotor (ver "Gotchas"). Pra confirmar que **o pipeline em si**
está correto, use o `rotctl` — cliente de referência do hamlib, mesmo
protocolo:

```bash
sudo apt install -y libhamlib-utils
rotctl -m 2 -r <HOST_DO_GRS_MANAGER>:4533
```

```
p              # lê a posição atual
P 90 20        # comanda azimute=90°, elevação=20°
p              # confirma que mudou
```

## Testes automatizados

```powershell
pytest
```

- `tests/test_tracking_service.py` — clamp de curso do núcleo do Station Manager.
- `tests/test_grs_manager_rotctld_server.py` — protocolo rotctld do GRS Manager (com um duplo de `RotorControlUseCase`) e o rastreio de conexão do gpredict.
- `tests/test_rotor_zmq_server.py` — dispatch do servidor ZMQ do Station Manager (requer `pyzmq`; pula automaticamente se não estiver instalado).
- `tests/test_grs_manager_status_app.py` — painel de status (Flask test client, com duplos — não precisa de ZMQ real).
- `tests/test_rotor_pipeline_integration.py` — os dois serviços rodando de verdade, falando ZMQ um com o outro, incluindo o painel de status refletindo o estado real (o teste mais próximo do cenário real).

## Gotchas descobertos na prática

- **`\dump_state`**: o backend NET rotctl do hamlib (usado pelo `rotctl -m 2`
  e pelo gpredict por baixo dos panos) manda esse comando assim que abre a
  conexão com o GRS Manager, esperando uma resposta específica com as
  capacidades do rotor. Sem isso, a conexão falha com "Protocol error".
- **Cycle do gpredict**: o padrão de 10ms sobrecarrega o Rotor Manager (que
  não correlaciona pedido/resposta de status — ver docstring de
  `rot2prog_zmq.py`), causando reconexões em loop entre gpredict e GRS
  Manager. Usar 20ms ou mais resolve.
- **Precisão de 1 grau**: o protocolo Rot2Prog, do jeito que está codificado
  em `grs-rotor-manager` hoje, só transmite graus inteiros (bytes de "pulse"
  fixos em 1 pulso/grau). O Station Manager preserva a precisão decimal
  completa (ver log `TrackingService: Alvo após clamp...`) até entregar pro
  Rotor Manager — o truncamento acontece só na codificação do pacote
  binário, do lado do submódulo.
- **Context ZMQ compartilhado trava no Windows**: usar `zmq.Context.instance()`
  (o singleton global) em vários sockets/threads que abrem e fecham rápido
  causou um crash nativo (`Assertion failed: pfd.revents & POLLIN`,
  `signaler.cpp`) durante os testes automatizados no Windows. Corrigido
  usando um `zmq.Context()` dedicado por serviço (`RotorZmqServer`,
  `StationManagerZmqClient`), cada um fechado (`socket.close()` +
  `context.term()`) explicitamente no shutdown.
- **Bug conhecido do próprio gpredict**: crash com `GLib-CRITICAL:
  g_hash_table_get_keys: assertion 'hash_table != NULL' failed` ao encerrar a
  conexão (Ctrl+C). É um bug do gpredict (relacionado a
  [issue #253](https://github.com/csete/gpredict/issues/253) do projeto),
  não do nosso pipeline — confirmado rodando `rotctl` (que não apresenta
  esse problema) contra o mesmo GRS Manager.
