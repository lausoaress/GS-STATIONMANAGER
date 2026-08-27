# Modelo de banco de dados — Station Manager

O MGM8 utiliza o PostgreSQL (com TimescaleDB no ecossistema GRS) e define o schema **`station_manager`** para dados operacionais. Dados de telemetria de alta frequência permanecem em `telemetry_stream`; metadados de missão em `mission_control`.

## Diagrama entidade-relacionamento

```mermaid
erDiagram
    SATELLITES_MC ||--o{ SCHEDULED_PASSES : "referencia"
    SCHEDULED_PASSES ||--o{ PASS_EXECUTIONS : "executa"
    SCHEDULED_PASSES ||--o{ SCHEDULED_TELECOMMANDS : "pode conter"
    SCHEDULED_TELECOMMANDS ||--o{ TELECOMMAND_EXECUTIONS : "executa"
    SCHEDULED_PASSES ||--o{ SCHEDULING_CONFLICTS : "envolvido"

    CONNECTED_APPLICATIONS ||--o{ APPLICATION_CONNECTIONS : "historico"
    CONNECTED_APPLICATIONS ||--o{ APPLICATION_HEALTH_SNAPSHOTS : "monitora"

    STATION_STATE ||--o{ STATION_STATE_HISTORY : "evolui"
    CONFIGURATION_PARAMETERS ||--o{ CONFIGURATION_HISTORY : "auditoria"

    AUTONOMOUS_SESSIONS ||--o{ PASS_EXECUTIONS : "coordena"
    REMOTE_COMMANDS ||--o{ REMOTE_COMMAND_EXECUTIONS : "executa"

    OPERATIONAL_EVENTS }o--|| SATELLITES_MC : "opcional"
    OPERATIONAL_EVENTS }o--|| SCHEDULED_PASSES : "opcional"

    SATELLITES_MC {
        uuid id PK "mission_control.satellites"
        varchar name
    }

    SCHEDULED_PASSES {
        uuid id PK
        uuid satellite_id FK
        timestamptz aos
        timestamptz los
        bigint center_frequency_hz
        varchar status
        varchar created_by
        timestamptz created_at
    }

    PASS_EXECUTIONS {
        uuid id PK
        uuid scheduled_pass_id FK
        uuid autonomous_session_id FK
        varchar status
        timestamptz started_at
        timestamptz ended_at
        text failure_reason
    }

    SCHEDULED_TELECOMMANDS {
        uuid id PK
        uuid scheduled_pass_id FK
        uuid telecommand_definition_id FK
        timestamptz execute_at
        varchar status
        int priority
    }

    TELECOMMAND_EXECUTIONS {
        uuid id PK
        uuid scheduled_telecommand_id FK
        varchar status
        timestamptz executed_at
        bytea raw_frame
        text response
    }

    SCHEDULING_CONFLICTS {
        uuid id PK
        uuid pass_a_id FK
        uuid pass_b_id FK
        varchar resource
        timestamptz detected_at
        varchar resolution
    }

    CONNECTED_APPLICATIONS {
        uuid id PK
        varchar name
        varchar component_type
        varchar zmq_address
        varchar version
        boolean is_critical
    }

    APPLICATION_CONNECTIONS {
        bigserial id PK
        uuid application_id FK
        varchar event_type
        timestamptz occurred_at
        text details
    }

    APPLICATION_HEALTH_SNAPSHOTS {
        bigserial id PK
        uuid application_id FK
        timestamptz checked_at
        varchar status
        int latency_ms
        text last_error
    }

    STATION_STATE {
        smallint id PK "singleton row id=1"
        varchar operational_mode
        uuid active_pass_id FK
        uuid active_satellite_id FK
        jsonb subsystem_status
        timestamptz updated_at
    }

    STATION_STATE_HISTORY {
        bigserial id PK
        timestamptz recorded_at
        varchar operational_mode
        jsonb state_snapshot
    }

    CONFIGURATION_PARAMETERS {
        uuid id PK
        varchar key UK
        jsonb value
        varchar category
        boolean requires_restart
        timestamptz updated_at
    }

    CONFIGURATION_HISTORY {
        bigserial id PK
        uuid parameter_id FK
        jsonb old_value
        jsonb new_value
        varchar changed_by
        timestamptz changed_at
    }

    AUTONOMOUS_SESSIONS {
        uuid id PK
        timestamptz started_at
        timestamptz ended_at
        varchar status
        text notes
    }

    REMOTE_COMMANDS {
        uuid id PK
        varchar source
        varchar action
        jsonb payload
        varchar status
        timestamptz received_at
    }

    REMOTE_COMMAND_EXECUTIONS {
        uuid id PK
        uuid remote_command_id FK
        uuid target_application_id FK
        varchar status
        timestamptz started_at
        timestamptz completed_at
        jsonb response
    }

    OPERATIONAL_EVENTS {
        bigserial id PK
        timestamptz occurred_at
        varchar severity
        varchar category
        varchar message
        uuid satellite_id FK
        uuid pass_id FK
        jsonb metadata
    }

    SYSTEM_LOGS {
        bigserial id PK
        timestamptz logged_at
        varchar level
        varchar logger
        text message
        jsonb context
    }
```

## Schemas e segregação

| Schema | Propósito | Escrita por |
|--------|-----------|-------------|
| `station_manager` | Operações, agenda, estado, logs operacionais | MGM8 |
| `mission_control` | Dimensões: satélites, pacotes, definições TC | Database / TC Generator |
| `telemetry_stream` | Hypertables de telemetria | Decoders |

## Tabelas — resumo

| Tabela | Tipo | Descrição |
|--------|------|-----------|
| `scheduled_passes` | Dimensão operacional | Passagens de satélite agendadas |
| `pass_executions` | Fato | Execuções reais de passagens |
| `scheduled_telecommands` | Dimensão operacional | TCs agendados |
| `telecommand_executions` | Fato | TCs executados |
| `scheduling_conflicts` | Auditoria | Conflitos detectados |
| `connected_applications` | Registro | Apps monitorados (IQ, rotor, etc.) |
| `application_connections` | Histórico | Conexões/desconexões |
| `application_health_snapshots` | Time-series leve | Health checks periódicos |
| `station_state` | Singleton | Estado atual (1 linha) |
| `station_state_history` | Histórico | Snapshots de estado |
| `configuration_parameters` | Config | Parâmetros operacionais |
| `configuration_history` | Auditoria | Alterações de config |
| `autonomous_sessions` | Sessão | Períodos de operação autônoma |
| `remote_commands` | Comando | Comandos recebidos do GRS |
| `remote_command_executions` | Fato | Execução de comandos remotos |
| `operational_events` | Event log | Eventos operacionais |
| `system_logs` | Log técnico | Logs estruturados do MGM8 |

## Índices principais

- `scheduled_passes (aos, los)` — consultas de agenda e conflitos
- `scheduled_passes (status)` — passagens pendentes
- `scheduled_telecommands (execute_at)` — disparo pelo scheduler
- `operational_events (occurred_at DESC)` — consultas recentes
- `application_health_snapshots (application_id, checked_at DESC)`
- `station_state_history (recorded_at DESC)`

## Script SQL

> **Este documento descreve um design, não o banco em uso.** O script está em
> [`design-original-mgm8.sql`](design-original-mgm8.sql) e nada o executa: o
> schema que a estação realmente usa é o do TC Generator
> (`services/grs-tc-generator/resources/database/schema.sql`), montado pelo
> compose em `/docker-entrypoint-initdb.d/`. As tabelas que o TC Scheduler
> escreve e serve — `satellites`, `telecommands`, `scheduled_passes`,
> `satellite_tracking_status`, `execution_logs` — estão lá, e não aqui.

Se ainda assim quiser aplicar o design original num banco separado:

```bash
psql -U grs -d grs -f docs/database/design-original-mgm8.sql
```

## Valores enumerados

### `operational_mode` (station_state)
`Offline` | `Initializing` | `Idle` | `Manual` | `Autonomous` | `PassActive` | `Degraded` | `Maintenance`

### `pass_status` (scheduled_passes)
`Scheduled` | `Cancelled` | `InProgress` | `Completed` | `Failed` | `Missed`

### `execution_status` (pass_executions, telecommand_executions)
`Pending` | `Started` | `Completed` | `Failed` | `Aborted`

### `health_status` (application_health_snapshots)
`Healthy` | `Degraded` | `Unhealthy` | `Unknown`

### `event_severity` (operational_events)
`DEBUG` | `INFO` | `WARNING` | `ERROR` | `CRITICAL`

## Consultas operacionais comuns

### Passagens nas próximas 24h

```sql
SELECT sp.id, s.name AS satellite, sp.aos, sp.los, sp.status
FROM station_manager.scheduled_passes sp
JOIN mission_control.satellites s ON s.id = sp.satellite_id
WHERE sp.aos BETWEEN now() AND now() + interval '24 hours'
  AND sp.status = 'Scheduled'
ORDER BY sp.aos;
```

### Detectar conflitos de agenda

```sql
SELECT a.id AS pass_a, b.id AS pass_b, a.aos, a.los, b.aos, b.los
FROM station_manager.scheduled_passes a
JOIN station_manager.scheduled_passes b
  ON a.id < b.id
 AND a.status = 'Scheduled'
 AND b.status = 'Scheduled'
 AND a.aos < b.los
 AND b.aos < a.los;
```

### Estado atual da estação

```sql
SELECT operational_mode, subsystem_status, updated_at
FROM station_manager.station_state
WHERE id = 1;
```

## Evolução futura

- Hypertable em `station_state_history` e `application_health_snapshots` se volume crescer
- Particionamento de `operational_events` por mês
- Views materializadas para dashboard Grafana
- Políticas de retenção (ex.: logs > 90 dias → archive)
