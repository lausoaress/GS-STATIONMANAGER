# Ground Station Manager (MGM8)

Gerenciador de operações da estação terrestre do SpaceLab — middleware central entre o **GRS Manager** (Control Desktop) e os microserviços do **Station Server** (Control Server).

## Aplicação Python / Flask

O projeto usa Python 3.11+ e Flask, mantendo a arquitetura hexagonal documentada em [docs/architecture/application-layers.md](docs/architecture/application-layers.md).

```
src/mgm8/
├── api/             # Adaptador HTTP Flask
├── application/     # Casos de uso (agendamento de passagens, descoberta via TLE)
├── domain/          # Entidades, value objects, portas e regras de negócio
├── infrastructure/  # Adaptadores (persistência em memória, propagador Skyfield)
└── web/             # Interface web Mission Control (Jinja2)
tests/               # Testes pytest
```

### Executar localmente

```powershell
.\run.ps1
```

O script cria o `.venv` se necessário, instala as dependências e sobe o Flask em `http://127.0.0.1:5000`. Para outra porta: `.\run.ps1 -Port 5001`.

Alternativa manual:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
flask --app mgm8.api.app run --debug
```

A API expõe:

| Rota | Descrição |
|------|-----------|
| `GET /health` | Liveness check |
| `POST /api/passes` | Agenda uma passagem manualmente |
| `POST /api/passes/predict` | Prevê passagens a partir de um TLE (satellite tracker próprio) |
| `POST /api/passes/discover` | Prevê e agenda automaticamente as passagens de um satélite |
| `GET` / `POST /api/telecommands` | Lista e agenda transmissões de telecomando |
| `POST /api/telecommands/<id>/approve` e `/cancel` | Aprova ou cancela um telecomando agendado |

Os dois últimos precisam do extra de propagação: `pip install -e ".[propagation]"`
(já incluso em `.[dev]`). Sem ele, respondem `503`. Detalhes em
[docs/architecture/propagation.md](docs/architecture/propagation.md).

A interface web Mission Control (adaptada do [grs-tc-generator](https://github.com/spacelab-ufsc/grs-tc-generator)) está disponível em `GET /`.

### Testes

```powershell
pytest
```

## Documentação

Toda a modelagem de arquitetura está em [`docs/`](docs/README.md).

## Licença

GPL-3.0
