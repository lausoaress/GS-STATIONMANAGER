# Ground Station Manager (MGM8)

Gerenciador de operações da estação terrestre do SpaceLab — middleware central entre o **GRS Manager** (Control Desktop) e os microserviços do **Station Server** (Control Server).

## Aplicação Python / Flask

O projeto usa Python 3.11+ e Flask, mantendo a arquitetura hexagonal documentada em [docs/architecture/application-layers.md](docs/architecture/application-layers.md).

```
src/mgm8/
├── api/             # Adaptador HTTP Flask
├── application/     # Casos de uso
├── domain/          # Entidades, value objects, portas e regras de negócio
└── infrastructure/  # Adaptadores de persistência (em memória por enquanto)
tests/               # Testes pytest
```

### Executar localmente

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
flask --app mgm8.api.app run --debug
```

A API expõe `GET /health` e `POST /api/passes`. Veja o exemplo de payload em `tests/test_api.py`.

### Testes

```powershell
pytest
```

## Documentação

Toda a modelagem de arquitetura está em [`docs/`](docs/README.md).

## Licença

GPL-3.0
