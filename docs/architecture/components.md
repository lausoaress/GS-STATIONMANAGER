# Diagrama de componentes

Visão UML de componentes do MGM8 e suas dependências externas.

## Componentes internos do MGM8

```mermaid
flowchart TB
    subgraph MGM8["<<subsystem>> Station Manager (MGM8)"]
        direction TB

        subgraph Inbound["Adapters de entrada"]
            C_GRSA["<<component>>\nGRS Adapter"]
            C_ZMQSub["<<component>>\nZMQ Status Subscriber"]
            C_Sched["<<component>>\nScheduler Worker"]
            C_Health["<<component>>\nHealth Poller"]
        end

        subgraph Core["Núcleo de aplicação"]
            C_Router["<<component>>\nMessage Router"]
            C_PassSch["<<component>>\nPass Scheduler"]
            C_TCSch["<<component>>\nTC Scheduler"]
            C_Auto["<<component>>\nAutonomous Operation"]
            C_State["<<component>>\nState Publisher"]
            C_Config["<<component>>\nConfig Service"]
            C_Events["<<component>>\nEvent Logger"]
        end

        subgraph Outbound["Adapters de saída"]
            C_SS["<<component>>\nStation Server Adapter"]
            C_Repo["<<component>>\nPostgreSQL Repository"]
            C_Notify["<<component>>\nGRS Notifier"]
            C_Trans["<<component>>\nProtocol Translators"]
        end
    end

    GRS_EXT["GRS Manager"]
    PG_EXT[("PostgreSQL")]
    SS_EXT["Station Server\nApps"]

    GRS_EXT --> C_GRSA
    C_GRSA --> C_Router
    C_ZMQSub --> C_State
    C_Sched --> C_PassSch
    C_Sched --> C_TCSch
    C_Health --> C_Events

    C_Router --> C_Trans
    C_Trans --> C_SS
    C_PassSch --> C_Auto
    C_TCSch --> C_Auto
    C_Auto --> C_SS
    C_Auto --> C_Events

    C_Router --> C_Repo
    C_PassSch --> C_Repo
    C_TCSch --> C_Repo
    C_Events --> C_Repo
    C_Config --> C_Repo
    C_State --> C_Repo
    C_State --> C_Notify
    C_Notify --> GRS_EXT
    C_SS --> SS_EXT
    C_Repo --> PG_EXT
```

## Interfaces (ports) expostas

| Componente | Porta | Protocolo | Consumidor |
|------------|-------|-----------|------------|
| GRS Adapter | `IGRSCommandPort` | ZMQ REQ/REP | GRS Manager |
| GRS Notifier | `IStationStatePort` | ZMQ PUB | GRS Manager |
| Station Server Adapter | `IStationCommandPort` | ZMQ PUSH/REQ/PUB | Microserviços SS |
| PostgreSQL Repository | `IStationRepository` | SQL/asyncpg | Todos os services |
| Protocol Translators | `IProtocolTranslator` | In-process | Message Router |

## Diagrama de pacotes

```mermaid
flowchart LR
    subgraph pkg_adapters ["adapters"]
        inbound["inbound"]
        outbound["outbound"]
    end

    subgraph pkg_application ["application"]
        services["services / use cases"]
    end

    subgraph pkg_domain ["domain"]
        entities["entities"]
        ports["ports (interfaces)"]
    end

    inbound --> services
    services --> entities
    services --> ports
    outbound -.->|implements| ports
    inbound -.->|implements| ports
```

## Dependências externas

```mermaid
flowchart LR
    MGM8["MGM8"]

    PYZMQ["pyzmq"]
    ASYNCPG["asyncpg / SQLAlchemy"]
    APSCHED["APScheduler"]
    PYDANTIC["pydantic"]
    STRUCTLOG["structlog"]

    MGM8 --> PYZMQ
    MGM8 --> ASYNCPG
    MGM8 --> APSCHED
    MGM8 --> PYDANTIC
    MGM8 --> STRUCTLOG
```

| Biblioteca | Uso |
|------------|-----|
| **pyzmq** | Comunicação com GRS Manager e Station Server |
| **asyncpg** | Acesso assíncrono ao PostgreSQL |
| **APScheduler** | Disparo de passagens e TCs agendados |
| **pydantic** | Validação de mensagens e DTOs |
| **structlog** | Logs estruturados → `system_logs` |
