# Diagrama de implantação

## Visão física

A estação terrestre GRS distribui a carga em três segmentos, tipicamente em máquinas distintas na rede local da estação.

```mermaid
flowchart TB
    subgraph LAN["Rede local da estação (LAN)"]
        subgraph M1["Máquina: Control Desktop"]
            OS1["SO: Linux / Windows"]
            GRS["GRS Manager"]
            GP["GPredict"]
            TCGen["TC Generator (browser)"]
            Browser["Dashboard Grafana"]
        end

        subgraph M2["Máquina: Control Server"]
            OS2["SO: Linux"]
            MGM["Station Manager (MGM8)"]
            PG[("PostgreSQL 16\n+ TimescaleDB")]
            Decoders["DL/Network Decoders"]
            Encoders["DL/Network Encoders"]
            TCSched["Satellite TC Scheduler"]
        end

        subgraph M3["Máquina: Station Server"]
            OS3["SO: Linux"]
            IQ["IQ Receiver"]
            FFT["GRS FFT"]
            Dem["Demodulator"]
            SWDet["Syncword Detector"]
            Rotor["Rotor Manager"]
            FreqSyn["Frequency Synthesizer"]
            RFFe["RF Front-End Controller"]
        end

        subgraph HW["Hardware RF"]
            SDR["SDR (RTL / Pluto / USRP)"]
            Amp["Amplificador / LNA"]
            Rotator["Rotor AlfaSpid RAS-2"]
            Antenna["Antena"]
        end
    end

    GRS <-->|"TCP ZMQ\n5555-5560"| MGM
    MGM <-->|"TCP ZMQ\n5570-5590"| M3
    MGM --> PG
    Decoders --> PG
    TCSched --> Encoders
    Encoders --> M3
    M3 --> Decoders
    IQ <-->|"USB/Ethernet"| SDR
    Rotor <-->|"Serial / ZMQ sim"| Rotator
    RFFe --> Amp
    SDR --> Antenna
    GP -.->|"TLE / passagens"| GRS
    Browser -.->|"HTTP 3000"| PG
```

## Nós de implantação

| Nó | Componentes | Recursos mínimos sugeridos |
|----|-------------|----------------------------|
| **Control Desktop** | GRS Manager, GPredict, browsers | 4 CPU, 8 GB RAM, GPU opcional |
| **Control Server** | MGM8, PostgreSQL, decoders, encoders | 8 CPU, 16 GB RAM, SSD |
| **Station Server** | Pipeline RF/DSP em tempo real | 4 CPU, 8 GB RAM, baixa latência USB |

## Diagrama UML de implantação

```mermaid
flowchart LR
    subgraph node_cd ["<<device>> Control Desktop"]
        artifact_grs["<<artifact>> grs-manager"]
        artifact_gp["<<artifact>> gpredict"]
    end

    subgraph node_cs ["<<device>> Control Server"]
        artifact_mgm["<<artifact>> mgm8"]
        artifact_pg["<<artifact>> postgresql-timescaledb"]
        artifact_dec["<<artifact>> grs-decoders"]
    end

    subgraph node_ss ["<<device>> Station Server"]
        artifact_iq["<<artifact>> iq-receiver"]
        artifact_pipeline["<<artifact>> signal-pipeline"]
        artifact_rotor["<<artifact>> rotor-manager"]
    end

    artifact_grs -->|"ZMQ TCP"| artifact_mgm
    artifact_mgm --> artifact_pg
    artifact_mgm -->|"ZMQ TCP"| artifact_iq
    artifact_mgm -->|"ZMQ TCP"| artifact_rotor
    artifact_iq --> artifact_pipeline
    artifact_dec --> artifact_pg
```

## Mapa de portas e endpoints ZMQ (proposta)

| Serviço | Endereço ZMQ | Padrão | Direção |
|---------|--------------|--------|---------|
| GRS Manager ↔ MGM8 (comandos) | `tcp://control-server:5555` | REQ/REP | Bidirecional |
| MGM8 → GRS (estado) | `tcp://control-server:5556` | PUB/SUB | MGM8 publica |
| MGM8 → IQ Receiver (tune) | `tcp://station-server:5570` | PUB | MGM8 publica |
| MGM8 → Rotor Manager | `tcp://station-server:5571` | PUSH | MGM8 envia |
| Rotor status | `tcp://station-server:5572` | SUB | MGM8 assina |
| Health/status pipeline | `tcp://station-server:5580` | PUB/SUB | Apps publicam |
| Frequency Synthesizer | `tcp://station-server:5575` | SUB/PUB | Interno SS |

> Os endereços exatos devem ser externalizados via variáveis de ambiente ou arquivo de configuração.

## Implantação com containers (opcional)

```mermaid
flowchart TB
    subgraph docker_cs ["Control Server — Docker Compose"]
        svc_mgm["service: mgm8"]
        svc_pg["service: postgres-timescaledb"]
        svc_dec["service: decoders"]
        svc_mgm --> svc_pg
        svc_dec --> svc_pg
    end

    subgraph docker_ss ["Station Server — Docker / bare metal"]
        svc_iq["service: iq-receiver"]
        svc_dsp["service: dsp-pipeline"]
        svc_rotor["service: rotor-manager"]
    end

    svc_mgm <-->|"host network ou bridge"| svc_iq
```

**Recomendação:** componentes de tempo real (IQ Receiver, demodulador) devem rodar em **bare metal** ou com acesso USB direto; MGM8 e PostgreSQL podem ser containerizados.

## Variáveis de ambiente (MGM8)

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `MGM_DATABASE_URL` | Connection string PostgreSQL | `postgresql://mgm:pass@localhost:5432/grs` |
| `MGM_ZMQ_GRS_REP` | Bind/endereço REQ/REP GRS | `tcp://0.0.0.0:5555` |
| `MGM_ZMQ_STATE_PUB` | Bind PUB estado | `tcp://0.0.0.0:5556` |
| `MGM_ZMQ_STATION_SERVER` | Endereço base Station Server | `tcp://192.168.1.20` |
| `MGM_AUTONOMOUS_ENABLED` | Habilita operação autônoma | `true` |
| `MGM_LOG_LEVEL` | Nível de log | `INFO` |

## Requisitos de rede

- Latência baixa entre Control Server e Station Server (< 5 ms na LAN)
- Portas ZMQ liberadas entre os três segmentos
- PostgreSQL acessível apenas pelo Control Server (não expor à internet)
- GPredict pode rodar localmente no Desktop; TLEs sincronizados manualmente ou via API

## Alta disponibilidade (fase futura)

| Aspecto | Estratégia |
|---------|------------|
| PostgreSQL | Réplica streaming + backup diário |
| MGM8 | Restart automático (systemd / Docker restart policy) |
| Station Server | Watchdog nos processos de pipeline |
| Estado | Recuperação de passagem interrompida via `pass_executions` |
