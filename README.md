> **Arquivado em 2026-09-11.** A estação agora vive em repositórios separados,
> na organização [`nanosat-gs`](https://github.com/nanosat-gs) — comece por
> [`nanosat-gs/grs-station`](https://github.com/nanosat-gs/grs-station). O que
> foi para onde, e por quê, está em [ARCHIVED.md](ARCHIVED.md). O conteúdo
> abaixo descreve a estação como ela era antes da divisão.

# Ground Station Manager (MGM8)

Gerenciador de operações da estação terrestre do SpaceLab — middleware central entre o **GRS Manager** (Control Desktop) e os microserviços do **Station Server** (Control Server).

## Aplicação Python / Flask

O projeto usa Python 3.11+ e Flask, mantendo a arquitetura hexagonal documentada em [docs/architecture/application-layers.md](docs/architecture/application-layers.md).

```
src/mgm8/            # Station Manager (Control Server)
├── application/     # Casos de uso: controle de rotor e rastreamento de passagem
├── domain/          # Entidades, value objects, portas e regras de negócio
├── infrastructure/  # Adaptadores de saída (rotor mock/ZMQ, apontamento SGP4)
└── rotor_zmq/       # Adaptador de entrada ZMQ: única porta de rede do serviço

src/tc_scheduler/    # TC Scheduler (Control Server) — decide o que rastrear
├── planner.py       # Escolha de passagens: onde mora a autonomia
├── db.py            # Leitura/escrita no banco do TC Generator (SQL puro)
├── station_data.py  # Leitura do plano, para servir a quem pergunta
├── api.py           # API HTTP de leitura (:5591) — é daqui que o painel se serve
└── station_manager.py  # Cliente ZMQ pro Station Manager

libs/spacelab-tracking/  # Satellite Tracker — SGP4, CelesTrak, previsão de passagens

src/grs_manager/      # GRS Manager (Control Desktop) — processo separado
├── domain/          # Portas e value objects próprios (não compartilha código com o mgm8)
├── rotctld/         # Adaptador de entrada: bridge TCP compatível com rotctld (gpredict)
├── adapters/        # Adaptador de saída: cliente ZMQ pro Station Manager
├── status/          # Painel HTTP (Flask): rotor respondendo? plano da estação?
└── status/scheduler_client.py  # Cliente da API do TC Scheduler (não abre banco)

services/            # Submódulos git — outros blocos da estação, orquestrados pelo compose
└── grs-tc-generator/    # Satellite TC Generator (Control Desktop)

src/mgm8/vendor/     # Rotor Manager copiado do grs-rotor-manager (ver UPSTREAM.md)
docker/              # Dockerfile da imagem que serve mgm8 e grs_manager
tests/               # Testes pytest
tools/               # Scripts de diagnóstico (ex.: rotctld_spy.py)
```

## Subir a estação completa (Docker)

Este repositório é o **orquestrador**: o `docker-compose.yml` da raiz é o único
compose da estação integrada. Cada bloco continua sendo um repositório
independente, com o seu próprio Dockerfile e o seu próprio compose para rodar
sozinho — o orquestrador não importa o compose de ninguém, apenas declara a
infra compartilhada (um postgres, uma rede) e constrói cada serviço a partir do
submódulo correspondente em `services/`.

```powershell
git submodule update --init --recursive
cp .env.example .env
docker compose up -d --build
```

| Serviço | Porta | O que é |
|---|---|---|
| `tc-generator-web` | 5000 | Interface web de telecomandos |
| `pgadmin` | 5050 | Administração do banco |
| `postgres` | 5432 | Banco `tc_generator`, compartilhado |
| `grs-manager` | 4533 | rotctld (hamlib) — **é aqui que o gpredict conecta** |
| `grs-manager` | 5590 | Painel de status ao vivo |
| `station-manager` | 5580 | ZMQ REP — comandos de rotor e rastreamento |
| `tc-scheduler` | — | Decide o que rastrear (sem porta: só consome) |

O `station-manager` sobe com `--rotor mock`. O caminho Rot2Prog real não
funciona entre containers porque o `RotorManager` vendorizado tem o socket SUB
fixo em `tcp://localhost:5560`; para rodar contra o rotor físico ou o simulador,
use os processos locais descritos abaixo.

As mudanças de schema do banco só são aplicadas na **primeira** subida de um
volume vazio (`docker-entrypoint-initdb.d`). Para reaplicar do zero:
`docker compose down -v` — isso **apaga** os dados existentes.

### Operação autônoma

Dois modos convivem, e os dois terminam no mesmo rotor:

- **Manual**: o gpredict conecta no GRS Manager (rotctld), que repassa cada
  setpoint ao Station Manager. Um humano decide o que acompanhar.
- **Autônomo**: o TC Scheduler lê os telecomandos pendentes, prevê as passagens
  dos satélites correspondentes e entrega a passagem inteira ao Station Manager
  numa ordem só (`track_satellite`), que conduz o apontamento até o LOS.

O laço de tempo real fica no Station Manager, e não no Scheduler, para que um
replanejamento pesado não atrase o rotor e para que uma queda do Scheduler no
meio de uma passagem não a interrompa.

Para habilitar o agendamento automático, cada satélite precisa de dados
orbitais — o `norad_id` fica nulo de propósito no seed, porque um identificador
errado faria a estação apontar para outro objeto sem nenhum erro visível:

```sql
UPDATE satellites SET norad_id = 25544 WHERE code = 'SAT-001';
```

Ajuste também as coordenadas da estação no `.env` (`GS_LATITUDE_DEG`,
`GS_LONGITUDE_DEG`, `GS_ALTITUDE_M`): os defaults são um exemplo de São Paulo.

Para conferir o cálculo orbital contra uma ferramenta independente:

```powershell
python -m spacelab_tracking.cli --norad-id 25544 --next-pass
python -m spacelab_tracking.cli --norad-id 25544 --export-tle iss.tle
```

Importe `iss.tle` no Gpredict e compare AOS, LOS e elevação máxima. Detalhes em
[`libs/spacelab-tracking/README.md`](libs/spacelab-tracking/README.md).

### Ver o fluxo funcionando

O fluxo autônomo acontece em três processos, então o estado fica espalhado
entre banco, scheduler e Station Manager. O monitor junta os três:

```powershell
docker compose exec tc-scheduler python -m tc_scheduler.monitor --watch
```

Mostra onde está cada satélite, o plano de passagens, o que o Station Manager
está rastreando, a posição do rotor e a fila de telecomandos — tudo no mesmo
retrato, atualizando a cada segundo.

Para exercitar o ciclo completo sem esperar a próxima passagem real (que pode
estar a horas de distância), `tools/station_demo.py`:

```powershell
# 1. Dá dados orbitais ao satélite e devolve os telecomandos à fila
docker compose exec tc-scheduler python tools/station_demo.py prepare --code SAT-001 --norad-id 25544

# 2. Força um replanejamento — este passo é real, com dados do CelesTrak
docker compose restart tc-scheduler
docker compose logs -f tc-scheduler

# 3. Acompanhe (em outro terminal)
docker compose exec tc-scheduler python -m tc_scheduler.monitor --watch

# 4. Dispara uma janela começando agora, em vez de esperar o AOS real
docker compose exec tc-scheduler python tools/station_demo.py simulate-pass --code SAT-001 --duration 120

# 5. Volta ao estado inicial quando terminar
docker compose exec tc-scheduler python tools/station_demo.py reset
```

O passo 4 é o único encenado: ele insere uma janela artificial (com os ângulos
reais do satélite naquele instante), pulando o planejador. Todo o resto do
caminho é o de produção — ativação no AOS, envio ao Station Manager,
apontamento e encerramento no LOS.

Se o satélite estiver abaixo do horizonte na hora do teste, o Station Manager
calcula o apontamento mas não move o rotor, porque seguir um alvo do outro lado
da Terra só castigaria o hardware. Para o rotor se mexer mesmo assim:

```powershell
$env:STATION_POINTING_MIN_ELEVATION="-90"; docker compose up -d station-manager
```

### Executar localmente (sem Docker)

```powershell
git submodule update --init --recursive
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "./libs/spacelab-tracking"
python -m pip install -e ".[dev,zmq,scheduler]"
python -m pytest
```

Nenhum dos serviços sobe com `flask run`: cada um tem o seu próprio `main`.
Veja as duas seções seguintes.

### Controle de rotor (gpredict -> GRS Manager -> Station Manager -> Rotor Manager)

Dois processos independentes (nem um, nem outro, sobem com `flask run`):

```powershell
# Terminal 1 — Station Manager: núcleo + adapter ZMQ de entrada (rotor mock)
python -m mgm8.rotor_zmq.main --rotor mock

# Terminal 2 — GRS Manager: fala rotctld (hamlib) pro gpredict, ZMQ pro Station Manager
python -m grs_manager.main
```

O gpredict conecta no **GRS Manager** (`127.0.0.1:4533`), nunca direto no
Station Manager. Para usar o rotor físico/simulado via ZMQ (protocolo
Rot2Prog de [`src/mgm8/vendor`](src/mgm8/vendor), copiado do
grs-rotor-manager) em vez do mock: `python -m mgm8.rotor_zmq.main --rotor zmq
--rotor-address tcp://127.0.0.1:5559` (requer `pip install -e ".[dev,zmq]"`).

O GRS Manager sobe junto o **painel do operador** — o dashboard do Station
Manager — em `http://127.0.0.1:5590` (`--status-port` pra mudar, `--no-status`
pra desligar): rotor ao vivo (Server-Sent Events), e, com `PG_DATABASE_URL`
configurado, satélites, próximas passagens e detalhe de cada satélite (vetor de
estado, ponto subsatélite, telecomandos da passagem). `GET /health` dá o estado
do rotor em JSON. Ver [`docs/architecture/painel-do-operador.md`](docs/architecture/painel-do-operador.md).

Guia completo (arquitetura, protocolos, teste com o simulador, configuração
do gpredict, teste entre duas máquinas, troubleshooting) em
[`docs/rotor-control.md`](docs/rotor-control.md).

### Testes

```powershell
pytest
```

## Documentação

Toda a modelagem de arquitetura está em [`docs/`](docs/README.md).

## Licença

GPL-3.0
