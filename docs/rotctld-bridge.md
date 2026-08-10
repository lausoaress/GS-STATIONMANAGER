# Bridge rotctld (gpredict → rotor)

Guia de setup e teste do módulo `mgm8.rotctld`: uma ponte que expõe uma
interface compatível com **rotctld** (protocolo de rotor do hamlib) para o
**gpredict** conectar como cliente, traduzindo os comandos de apontamento
para o rotor físico (AlfaSpid Rot2Prog) via ZMQ.

## Arquitetura

```
gpredict --(TCP, protocolo rotctld)--> mgm8.rotctld.server --> TrackingService --> RotorPort
                                                                                       |
                                                                    +------------------+------------------+
                                                                    |                                     |
                                                              MockRotor                          Rot2ProgZmqRotor
                                                          (em memória, sem                      (envolve RotorManager de
                                                           hardware)                              vendor/grs-rotor-manager,
                                                                                                    fala ZMQ com o rotor
                                                                                                    real ou o simulador)
```

- **Adapter de entrada**: [`src/mgm8/rotctld/server.py`](../src/mgm8/rotctld/server.py) — servidor TCP, implementa o subconjunto do protocolo rotctld que o gpredict usa.
- **Núcleo**: [`src/mgm8/application/tracking_service.py`](../src/mgm8/application/tracking_service.py) — faz o clamp de curso (limites de az/el) e loga o valor real (decimal, sem arredondar) que decide mandar pro rotor.
- **Adapters de saída**: [`src/mgm8/infrastructure/mock_rotor.py`](../src/mgm8/infrastructure/mock_rotor.py) (fake em memória) e [`src/mgm8/infrastructure/rot2prog_zmq.py`](../src/mgm8/infrastructure/rot2prog_zmq.py) (envolve o `RotorManager` real).
- **Composition root**: [`src/mgm8/rotctld/main.py`](../src/mgm8/rotctld/main.py) — único lugar que decide qual rotor concreto usar (`--rotor mock|zmq`).
- **Protocolo Rot2Prog / ZMQ**: implementado no submódulo git [`vendor/grs-rotor-manager`](../vendor/grs-rotor-manager) (repositório separado, `spacelab-ufsc/grs-rotor-manager`). O `mgm8` não duplica essa lógica — só traduz.

Este serviço é **independente** do Flask (`mgm8.api.app`) — subir um não sobe
o outro. Rode os dois processos separadamente se precisar dos dois.

## Pré-requisitos

```powershell
git submodule update --init --recursive   # baixa vendor/grs-rotor-manager
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Pra usar o rotor real ou o simulador via ZMQ (não o mock), instale também a
dependência opcional:

```powershell
python -m pip install -e ".[zmq]"
```

## Teste rápido (rotor mock, sem hardware)

Prova a ponte de ponta a ponta sem precisar de ZMQ nem do submódulo:

```powershell
python -m mgm8.rotctld.main --rotor mock
```

Isso sobe o servidor em `127.0.0.1:4533` (a porta padrão do rotctld/hamlib).
Aponte o gpredict (ou o `rotctl`, ver abaixo) pra esse host/porta.

Ferramenta de diagnóstico — imprime cada linha crua recebida, sem interpretar:

```powershell
python tools\rotctld_spy.py
```

## Teste completo (rotor via ZMQ + simulador)

Precisa de **dois terminais** na mesma máquina (o simulador finge ser o
hardware AlfaSpid Rot2Prog):

```powershell
# Terminal 1 — simulador do rotor
python -u vendor\grs-rotor-manager\rotor_simulator.py

# Terminal 2 — a ponte, apontando pro endereço de comandos (PUSH) do simulador
python -m mgm8.rotctld.main --rotor zmq --rotor-address tcp://127.0.0.1:5559
```

A porta de status (SUB, `5560`) é fixa dentro do próprio `RotorManager` e não
é configurável por aqui.

## Testar com uma máquina separada rodando o gpredict

Se o gpredict roda numa máquina diferente da que sobe a ponte (ex.: uma VM
Linux só com GUI), a ponte precisa escutar no IP da rede local, não em
`127.0.0.1`:

```powershell
# descobrir o IP desta máquina na rede que a máquina do gpredict alcança
ipconfig

python -m mgm8.rotctld.main --host <IP_DESTA_MAQUINA> --port 4533 --rotor zmq --rotor-address tcp://127.0.0.1:5559
```

Checklist se a conexão não chegar:
- **Firewall do Windows**: precisa permitir conexão de entrada pra `python.exe` na porta usada (o Windows costuma perguntar na primeira vez; se não perguntou, cheque `Get-NetFirewallRule -Direction Inbound | Where DisplayName -match python`).
- **Teste de conectividade a partir da máquina do gpredict**: `Test-NetConnection -ComputerName <IP> -Port 4533` (Windows) ou `nc -zv <IP> 4533` (Linux) antes mesmo de abrir o gpredict.
- Confirme que as duas máquinas estão na mesma sub-rede/alcançáveis por `ping`.

## Configurando o gpredict

No painel de configuração do rotor (**Edit → Preferences → Interfaces →
Rotators → Add New**, ou editando um existente):

| Campo | Valor |
|---|---|
| Host | IP da máquina rodando a ponte (ou `127.0.0.1` se for a mesma máquina) |
| Port | `4533` |
| Az type | `0° → 180° → 360°` |
| Min/Max Az | `0` / `360` |
| Min/Max El | `0` / `90` |
| **Cycle** | **≥ 20ms** — ver "Gotchas" abaixo, o padrão de 10ms quebra a conexão |

Depois, no módulo **Antenna Control**: selecione o rotor, clique **Engage**,
selecione um satélite no **Target** e clique **Track** pra rastreio
automático (só manda comando de movimento se o satélite estiver acima do
horizonte pra localização configurada).

## Verificando sem o gpredict (recomendado para validar a ponte isoladamente)

O `gpredict` tem bugs conhecidos e específicos de versão/plataforma no
controle de rotor (ver "Gotchas"). Pra confirmar que **a ponte em si** está
correta, use o `rotctl` — o cliente de linha de comando de referência do
próprio hamlib, que fala exatamente o mesmo protocolo:

```bash
# instalar (Debian/Ubuntu)
sudo apt install -y libhamlib-utils

# conectar (modelo 2 = "Hamlib NET rotctl", fala com qualquer rotctld)
rotctl -m 2 -r <HOST>:4533
```

No prompt interativo:
```
p              # lê a posição atual
P 90 20        # comanda azimute=90°, elevação=20°
p               # confirma que mudou
```

Se isso funcionar, a ponte está correta — qualquer problema restante é do
lado do cliente (gpredict), não da ponte.

## Testes automatizados

```powershell
pytest
```

Cobre o protocolo do `_dispatch` (incluindo `\dump_state`), o clamp de curso
do `TrackingService`, e o ciclo completo do servidor com um cliente socket
real (`tests/test_rotctld_server.py`, `tests/test_tracking_service.py`).

## Gotchas descobertos na prática

- **`\dump_state`**: o backend NET rotctl do hamlib (usado pelo `rotctl -m 2`
  e pelo gpredict por baixo dos panos) manda esse comando assim que abre a
  conexão, esperando uma resposta específica com as capacidades do rotor. Sem
  isso, a conexão falha com "Protocol error" — já implementado no servidor,
  mas é útil saber que esse comando existe se algum outro cliente hamlib
  apresentar o mesmo erro.
- **Cycle do gpredict**: o padrão de 10ms sobrecarrega o `RotorManager` (que
  não correlaciona pedido/resposta de status — ver docstring de
  `rot2prog_zmq.py`), causando reconexões em loop e o painel de posição nunca
  preenchendo. Usar 20ms ou mais resolve.
- **Precisão de 1 grau**: o protocolo Rot2Prog, do jeito que está codificado
  em `grs-rotor-manager` hoje, só transmite graus inteiros (bytes de "pulse"
  fixos em 1 pulso/grau). O `mgm8` preserva a precisão decimal completa até
  entregar pro `RotorManager` — o truncamento acontece só na codificação do
  pacote binário, do lado do submódulo. Resolução mais fina exigiria mudar
  `_encode_angle` em `grs-rotor-manager` E bater com a configuração física
  real do rotor (ajuste de pulsos/grau no hardware).
- **Leitura de posição pode ficar desatualizada por um ciclo**: como
  `RotorManager.request_status()` não correlaciona pedido/resposta, um
  `move_to`/`park` pode não refletir imediatamente na próxima leitura — se
  autocorrige no ciclo seguinte. Ver docstring de `rot2prog_zmq.py`.
- **Bug conhecido do próprio gpredict**: crash com `GLib-CRITICAL:
  g_hash_table_get_keys: assertion 'hash_table != NULL' failed` ao encerrar a
  conexão (Ctrl+C). É um bug do gpredict (relacionado a
  [issue #253](https://github.com/csete/gpredict/issues/253) do projeto),
  não da nossa ponte — confirmado rodando `rotctl` (que não apresenta esse
  problema) contra o mesmo servidor.
