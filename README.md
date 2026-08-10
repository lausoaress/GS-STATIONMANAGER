# Ground Station Manager (MGM8)

Gerenciador de operações da estação terrestre do SpaceLab — middleware central entre o **GRS Manager** (Control Desktop) e os microserviços do **Station Server** (Control Server).

## Aplicação Python / Flask

O projeto usa Python 3.11+ e Flask, mantendo a arquitetura hexagonal documentada em [docs/architecture/application-layers.md](docs/architecture/application-layers.md).

```
src/mgm8/
├── api/             # Adaptador HTTP Flask
├── application/     # Casos de uso
├── domain/          # Entidades, value objects, portas e regras de negócio
├── infrastructure/  # Adaptadores de saída (persistência em memória, rotor mock/ZMQ)
└── rotctld/         # Adaptador de entrada: bridge TCP compatível com rotctld (gpredict)
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

### Bridge rotctld (gpredict -> rotor)

Expõe uma interface compatível com rotctld (hamlib) para o gpredict conectar
como cliente e traduz os comandos de apontamento para o rotor físico
(AlfaSpid Rot2Prog via ZMQ, protocolo binário implementado em
[`vendor/grs-rotor-manager`](vendor/grs-rotor-manager), incluído como submódulo
git). É um processo independente do Flask — sobe com `python -m
mgm8.rotctld.main`, não com `flask run`.

```powershell
# com rotor mock (ouve em 127.0.0.1:4533)
python -m mgm8.rotctld.main --rotor mock

# com o rotor físico/simulado via ZMQ (requer: pip install -e ".[zmq]")
python -m mgm8.rotctld.main --rotor zmq --rotor-address tcp://127.0.0.1:5559
```

Guia completo (setup, teste com o simulador, configuração do gpredict,
teste entre duas máquinas, troubleshooting) em
[`docs/rotctld-bridge.md`](docs/rotctld-bridge.md).

### Testes

```powershell
pytest
```

## Documentação

Toda a modelagem de arquitetura está em [`docs/`](docs/README.md).

## Licença

GPL-3.0
