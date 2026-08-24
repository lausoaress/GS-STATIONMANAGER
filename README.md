# Ground Station Manager (MGM8)

Gerenciador de operações da estação terrestre do SpaceLab — middleware central entre o **GRS Manager** (Control Desktop) e os microserviços do **Station Server** (Control Server).

## Aplicação Python / Flask

O projeto usa Python 3.11+ e Flask, mantendo a arquitetura hexagonal documentada em [docs/architecture/application-layers.md](docs/architecture/application-layers.md).

```
src/mgm8/            # Station Manager (Control Server)
├── api/             # Adaptador HTTP Flask (agendamento de passagens)
├── application/     # Casos de uso
├── domain/          # Entidades, value objects, portas e regras de negócio
├── infrastructure/  # Adaptadores de saída (persistência em memória, rotor mock/ZMQ)
└── rotor_zmq/        # Adaptador de entrada ZMQ: controle de rotor pro GRS Manager

src/grs_manager/      # GRS Manager (Control Desktop) — processo separado
├── domain/          # Portas e value objects próprios (não compartilha código com o mgm8)
├── rotctld/         # Adaptador de entrada: bridge TCP compatível com rotctld (gpredict)
├── adapters/        # Adaptador de saída: cliente ZMQ pro Station Manager
└── status/          # Painel HTTP (Flask): gpredict conectado? rotor respondendo?

services/            # Submódulos git — outros blocos da estação, orquestrados pelo compose
└── grs-tc-generator/    # Satellite TC Generator (Control Desktop)

vendor/grs-rotor-manager/  # Submódulo git — Rotor Manager (Station Server), protocolo Rot2Prog
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
| `station-manager` | 5580 | ZMQ REP — comandos de rotor |

O `station-manager` sobe com `--rotor mock`. O caminho Rot2Prog real não
funciona entre containers porque o `RotorManager` vendorizado tem o socket SUB
fixo em `tcp://localhost:5560`; para rodar contra o rotor físico ou o simulador,
use os processos locais descritos abaixo.

As mudanças de schema do banco só são aplicadas na **primeira** subida de um
volume vazio (`docker-entrypoint-initdb.d`). Para reaplicar do zero:
`docker compose down -v` — isso **apaga** os dados existentes.

### Executar localmente (sem Docker)

```powershell
git submodule update --init --recursive
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
flask --app mgm8.api.app run --debug
```

A API expõe `GET /health` e `POST /api/passes`. Veja o exemplo de payload em `tests/test_api.py`.

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
Rot2Prog do [`vendor/grs-rotor-manager`](vendor/grs-rotor-manager), submódulo
git) em vez do mock: `python -m mgm8.rotor_zmq.main --rotor zmq
--rotor-address tcp://127.0.0.1:5559` (requer `pip install -e ".[dev,zmq]"`).

O GRS Manager sobe junto um **painel de status** em
`http://127.0.0.1:5590` (`--status-port` pra mudar, `--no-status` pra
desligar), mostrando se o gpredict está conectado e se o rotor está
respondendo — atualiza ao vivo (Server-Sent Events), sem recarregar a
página. `GET /health` dá o mesmo dado em JSON, sob demanda.

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
