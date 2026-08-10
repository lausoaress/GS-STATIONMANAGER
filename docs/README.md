# Documentação — Ground Station Manager (MGM8)

Documentação de arquitetura, modelagem e design do **Gerenciador da Estação Terrestre** do SpaceLab.

## Índice

| Documento | Conteúdo |
|-----------|----------|
| [Visão geral da arquitetura](architecture/overview.md) | Contexto no ecossistema GRS, responsabilidades e fronteiras |
| [Camadas da aplicação](architecture/application-layers.md) | Arquitetura em camadas, módulos e fluxos internos |
| [Diagrama de implantação](architecture/deployment.md) | Nós físicos, rede, protocolos e portas |
| [Casos de uso](architecture/use-cases.md) | Atores, casos de uso e diagramas UML |
| [Modelo de banco de dados](database/README.md) | ERD, schemas, tabelas e scripts SQL |
| [Integração com subsistemas](architecture/integration.md) | ZMQ, GRS Manager e Station Server |
| [Controle de rotor (gpredict → GRS Manager → Station Manager → Rotor Manager)](rotor-control.md) | Arquitetura completa do pipeline, setup, configuração do gpredict e troubleshooting |

## Referências

- [Arquitetura de software GRS — SpaceLab](https://spacelab-ufsc.github.io/grs-doc/software.html)
- Repositório MGM8: Gerenciador central de orquestração da estação terrestre

## Convenções

- **Control Desktop** — Área de trabalho do operador (GRS Manager, GPredict, etc.)
- **Control Server** — Servidor de controle (Station Manager, decoders, PostgreSQL)
- **Station Server** — Servidor de estação (RF, SDR, rotor, demodulador)
