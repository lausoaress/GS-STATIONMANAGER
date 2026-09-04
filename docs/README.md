# Documentação — Ground Station Manager (MGM8)

Documentação de arquitetura, modelagem e design do **Gerenciador da Estação Terrestre** do SpaceLab.

## Índice

| Documento | Conteúdo |
|-----------|----------|
| [Visão geral da arquitetura](architecture/overview.md) | Contexto no ecossistema GRS, responsabilidades e fronteiras |
| [Camadas da aplicação](architecture/application-layers.md) | Arquitetura em camadas, módulos e fluxos internos |
| [Diagrama de implantação](architecture/deployment.md) | Nós físicos, rede, protocolos e portas |
| [Casos de uso](architecture/use-cases.md) | Atores, casos de uso e diagramas UML |
| [Propagação orbital — explicação acessível](architecture/propagation-explained.md) | O que foi feito no rastreador de satélite e por quê, em linguagem simples |
| [Propagação orbital — referência técnica](architecture/propagation.md) | Satellite tracker próprio (SGP4), Doppler e descoberta de passagens |
| [Agendamento de telecomando](architecture/telecommand-scheduling.md) | Agendar transmissões de TC, payload opaco, aprovação e regras de validação |
| [Modelo de banco de dados](database/README.md) | ERD, schemas, tabelas e scripts SQL |
| [Integração com subsistemas](architecture/integration.md) | ZMQ, GRS Manager e Station Server |

## Referências

- [Arquitetura de software GRS — SpaceLab](https://spacelab-ufsc.github.io/grs-doc/software.html)
- Repositório MGM8: Gerenciador central de orquestração da estação terrestre

## Convenções

- **Control Desktop** — Área de trabalho do operador (GRS Manager, GPredict, etc.)
- **Control Server** — Servidor de controle (Station Manager, decoders, PostgreSQL)
- **Station Server** — Servidor de estação (RF, SDR, rotor, demodulador)
