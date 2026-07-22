-- ============================================================================
-- Ground Station Manager (MGM8) — Database Schema
-- Schema: station_manager
-- Database: PostgreSQL 16+ (compatible with TimescaleDB ecosystem)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS station_manager;

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- ENUM Types
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE station_manager.operational_mode AS ENUM (
        'Offline', 'Initializing', 'Idle', 'Manual',
        'Autonomous', 'PassActive', 'Degraded', 'Maintenance'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE station_manager.schedule_status AS ENUM (
        'Scheduled', 'Cancelled', 'InProgress', 'Completed', 'Failed', 'Missed'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE station_manager.execution_status AS ENUM (
        'Pending', 'Started', 'Completed', 'Failed', 'Aborted'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE station_manager.health_status AS ENUM (
        'Healthy', 'Degraded', 'Unhealthy', 'Unknown'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE station_manager.event_severity AS ENUM (
        'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE station_manager.connection_event AS ENUM (
        'Connected', 'Disconnected', 'Reconnected', 'Timeout'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- Connected Applications Registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.connected_applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL UNIQUE,
    component_type  VARCHAR(64)  NOT NULL,  -- e.g. 'iq_receiver', 'rotor_manager'
    zmq_address     VARCHAR(256),
    version         VARCHAR(32),
    is_critical     BOOLEAN NOT NULL DEFAULT FALSE,
    description     TEXT,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS station_manager.application_connections (
    id              BIGSERIAL PRIMARY KEY,
    application_id  UUID NOT NULL REFERENCES station_manager.connected_applications(id),
    event_type      station_manager.connection_event NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    details         TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_connections_app_time
    ON station_manager.application_connections (application_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS station_manager.application_health_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    application_id  UUID NOT NULL REFERENCES station_manager.connected_applications(id),
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          station_manager.health_status NOT NULL DEFAULT 'Unknown',
    latency_ms      INTEGER,
    last_error      TEXT
);

CREATE INDEX IF NOT EXISTS idx_health_app_time
    ON station_manager.application_health_snapshots (application_id, checked_at DESC);

-- ---------------------------------------------------------------------------
-- Scheduling — Satellite Passes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.scheduled_passes (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    satellite_id            UUID NOT NULL,  -- FK → mission_control.satellites(id)
    aos                     TIMESTAMPTZ NOT NULL,
    los                     TIMESTAMPTZ NOT NULL,
    center_frequency_hz     BIGINT NOT NULL,
    doppler_source          VARCHAR(64) DEFAULT 'propagator',
    max_elevation_deg       NUMERIC(5,2),
    status                  station_manager.schedule_status NOT NULL DEFAULT 'Scheduled',
    auto_execute            BOOLEAN NOT NULL DEFAULT TRUE,
    notes                   TEXT,
    created_by              VARCHAR(128),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_pass_window CHECK (los > aos)
);

CREATE INDEX IF NOT EXISTS idx_scheduled_passes_aos
    ON station_manager.scheduled_passes (aos);
CREATE INDEX IF NOT EXISTS idx_scheduled_passes_status
    ON station_manager.scheduled_passes (status);
CREATE INDEX IF NOT EXISTS idx_scheduled_passes_window
    ON station_manager.scheduled_passes (aos, los);

-- ---------------------------------------------------------------------------
-- Scheduling — Telecommands
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.scheduled_telecommands (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_pass_id           UUID REFERENCES station_manager.scheduled_passes(id),
    telecommand_definition_id   UUID NOT NULL,  -- FK → mission_control.telecommands(id)
    execute_at                  TIMESTAMPTZ NOT NULL,
    status                      station_manager.schedule_status NOT NULL DEFAULT 'Scheduled',
    priority                    SMALLINT NOT NULL DEFAULT 5,
    requires_approval           BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by                 VARCHAR(128),
    approved_at                 TIMESTAMPTZ,
    created_by                  VARCHAR(128),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tc_execute_at
    ON station_manager.scheduled_telecommands (execute_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_tc_pass
    ON station_manager.scheduled_telecommands (scheduled_pass_id);

-- ---------------------------------------------------------------------------
-- Scheduling Conflicts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.scheduling_conflicts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pass_a_id       UUID NOT NULL REFERENCES station_manager.scheduled_passes(id),
    pass_b_id       UUID NOT NULL REFERENCES station_manager.scheduled_passes(id),
    resource        VARCHAR(64) NOT NULL DEFAULT 'rf_chain',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolution      VARCHAR(128),
    resolved_at     TIMESTAMPTZ,
    CONSTRAINT chk_different_passes CHECK (pass_a_id <> pass_b_id)
);

-- ---------------------------------------------------------------------------
-- Executions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.autonomous_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    status          station_manager.execution_status NOT NULL DEFAULT 'Started',
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS station_manager.pass_executions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_pass_id       UUID NOT NULL REFERENCES station_manager.scheduled_passes(id),
    autonomous_session_id   UUID REFERENCES station_manager.autonomous_sessions(id),
    status                  station_manager.execution_status NOT NULL DEFAULT 'Pending',
    started_at              TIMESTAMPTZ,
    ended_at                TIMESTAMPTZ,
    failure_reason          TEXT,
    metadata                JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pass_exec_scheduled
    ON station_manager.pass_executions (scheduled_pass_id);
CREATE INDEX IF NOT EXISTS idx_pass_exec_status
    ON station_manager.pass_executions (status);

CREATE TABLE IF NOT EXISTS station_manager.telecommand_executions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_telecommand_id    UUID NOT NULL REFERENCES station_manager.scheduled_telecommands(id),
    status                      station_manager.execution_status NOT NULL DEFAULT 'Pending',
    executed_at                 TIMESTAMPTZ,
    raw_frame                   BYTEA,
    response                    TEXT,
    metadata                    JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tc_exec_scheduled
    ON station_manager.telecommand_executions (scheduled_telecommand_id);

-- ---------------------------------------------------------------------------
-- Remote Commands (from GRS Manager)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.remote_commands (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          VARCHAR(64) NOT NULL DEFAULT 'grs_manager',
    action          VARCHAR(128) NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          station_manager.execution_status NOT NULL DEFAULT 'Pending',
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    correlation_id  UUID
);

CREATE INDEX IF NOT EXISTS idx_remote_commands_received
    ON station_manager.remote_commands (received_at DESC);

CREATE TABLE IF NOT EXISTS station_manager.remote_command_executions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remote_command_id       UUID NOT NULL REFERENCES station_manager.remote_commands(id),
    target_application_id   UUID REFERENCES station_manager.connected_applications(id),
    status                  station_manager.execution_status NOT NULL DEFAULT 'Pending',
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    response                JSONB
);

-- ---------------------------------------------------------------------------
-- Station State (singleton)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.station_state (
    id                  SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    operational_mode    station_manager.operational_mode NOT NULL DEFAULT 'Offline',
    active_pass_id      UUID REFERENCES station_manager.scheduled_passes(id),
    active_satellite_id UUID,
    subsystem_status    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO station_manager.station_state (id, operational_mode)
VALUES (1, 'Offline')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS station_manager.station_state_history (
    id                  BIGSERIAL PRIMARY KEY,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    operational_mode    station_manager.operational_mode NOT NULL,
    state_snapshot      JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_history_time
    ON station_manager.station_state_history (recorded_at DESC);

-- ---------------------------------------------------------------------------
-- Configuration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.configuration_parameters (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key                 VARCHAR(128) NOT NULL UNIQUE,
    value               JSONB NOT NULL,
    category            VARCHAR(64) NOT NULL DEFAULT 'general',
    description         TEXT,
    requires_restart    BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS station_manager.configuration_history (
    id              BIGSERIAL PRIMARY KEY,
    parameter_id    UUID NOT NULL REFERENCES station_manager.configuration_parameters(id),
    old_value       JSONB,
    new_value       JSONB NOT NULL,
    changed_by      VARCHAR(128),
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Default configuration parameters
INSERT INTO station_manager.configuration_parameters (key, value, category, description)
VALUES
    ('autonomous.enabled', 'true'::jsonb, 'autonomy', 'Habilita operação autônoma'),
    ('autonomous.min_elevation_deg', '5'::jsonb, 'autonomy', 'Elevação mínima para passagem autônoma'),
    ('health.check_interval_sec', '10'::jsonb, 'monitoring', 'Intervalo de health check'),
    ('health.retry_count', '3'::jsonb, 'monitoring', 'Tentativas antes de marcar UNHEALTHY'),
    ('zmq.grs_rep_address', '"tcp://0.0.0.0:5555"'::jsonb, 'network', 'Endereço ZMQ REQ/REP GRS'),
    ('zmq.state_pub_address', '"tcp://0.0.0.0:5556"'::jsonb, 'network', 'Endereço ZMQ PUB estado')
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Logging & Events
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS station_manager.operational_events (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity        station_manager.event_severity NOT NULL DEFAULT 'INFO',
    category        VARCHAR(64) NOT NULL,
    message         TEXT NOT NULL,
    satellite_id    UUID,
    pass_id         UUID REFERENCES station_manager.scheduled_passes(id),
    metadata        JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_operational_events_time
    ON station_manager.operational_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_operational_events_severity
    ON station_manager.operational_events (severity);

CREATE TABLE IF NOT EXISTS station_manager.system_logs (
    id              BIGSERIAL PRIMARY KEY,
    logged_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    level           VARCHAR(16) NOT NULL,
    logger          VARCHAR(128) NOT NULL,
    message         TEXT NOT NULL,
    context         JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_system_logs_time
    ON station_manager.system_logs (logged_at DESC);

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW station_manager.v_upcoming_passes AS
SELECT
    sp.id,
    sp.satellite_id,
    sp.aos,
    sp.los,
    sp.center_frequency_hz,
    sp.status,
    sp.auto_execute,
    EXTRACT(EPOCH FROM (sp.aos - now())) AS seconds_until_aos
FROM station_manager.scheduled_passes sp
WHERE sp.status = 'Scheduled'
  AND sp.los > now()
ORDER BY sp.aos;

CREATE OR REPLACE VIEW station_manager.v_application_health_latest AS
SELECT DISTINCT ON (h.application_id)
    h.application_id,
    a.name,
    a.component_type,
    h.status,
    h.latency_ms,
    h.last_error,
    h.checked_at
FROM station_manager.application_health_snapshots h
JOIN station_manager.connected_applications a ON a.id = h.application_id
ORDER BY h.application_id, h.checked_at DESC;

-- ---------------------------------------------------------------------------
-- Seed: default connected applications
-- ---------------------------------------------------------------------------
INSERT INTO station_manager.connected_applications (name, component_type, is_critical, description)
VALUES
    ('iq_receiver',       'station_server', TRUE,  'GRS IQ Receiver — aquisição SDR'),
    ('rotor_manager',     'station_server', TRUE,  'GRS Rotor Manager — controle de antena'),
    ('frequency_synth',   'station_server', TRUE,  'GRS Frequency Synthesizer — sintonia + Doppler'),
    ('demodulator',       'station_server', TRUE,  'GRS Demodulator — GMSK'),
    ('rf_frontend',       'station_server', FALSE, 'RF Front-End Controller'),
    ('grs_manager',       'control_desktop', FALSE, 'GRS Manager — interface operador'),
    ('dl_decoder',        'control_server', FALSE, 'Data Link Layer Decoder'),
    ('tc_scheduler',      'control_server', FALSE, 'Satellite TC Scheduler')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Optional: Foreign keys to mission_control (uncomment when schema exists)
-- ---------------------------------------------------------------------------
-- ALTER TABLE station_manager.scheduled_passes
--     ADD CONSTRAINT fk_pass_satellite
--     FOREIGN KEY (satellite_id) REFERENCES mission_control.satellites(id);
--
-- ALTER TABLE station_manager.scheduled_telecommands
--     ADD CONSTRAINT fk_tc_definition
--     FOREIGN KEY (telecommand_definition_id) REFERENCES mission_control.telecommands(id);

COMMENT ON SCHEMA station_manager IS 'Ground Station Manager (MGM8) operational data schema';
