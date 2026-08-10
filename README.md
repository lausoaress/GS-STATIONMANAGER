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

vendor/grs-rotor-manager/  # Submódulo git — Rotor Manager (Station Server), protocolo Rot2Prog
tests/               # Testes pytest
tools/               # Scripts de diagnóstico (ex.: rotctld_spy.py)
```

### Executar localmente

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
respondendo (via `GET /health`, JSON).

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
