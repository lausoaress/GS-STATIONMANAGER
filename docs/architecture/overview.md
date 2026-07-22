# Visão geral da arquitetura

## Contexto no ecossistema GRS

O **Ground Station Manager (MGM8)** é o middleware central no **Control Server**. Ele não controla hardware diretamente; coordina os microserviços do **Station Server** e expõe um ponto único de contato para o **GRS Manager** no **Control Desktop**.

```mermaid
flowchart TB
    subgraph CD["Control Desktop"]
        GRS["GRS Manager"]
        GP["GPredict"]
        TCGen["Satellite TC Generator"]
        Dash["Dashboard / Grafana"]
    end

    subgraph CS["Control Server"]
        MGM["Station Manager (MGM8)"]
        PG[("PostgreSQL + TimescaleDB")]
        Dec["Decoders / Encoders"]
        TCS["TC Scheduler"]
    end

    subgraph SS["Station Server"]
        IQ["IQ Receiver"]
        FFT["GRS FFT"]
        Dem["Demodulator"]
        SW["Syncword Detector"]
        Rotor["Rotor Manager"]
        Freq["Frequency Synthesizer"]
        RF["RF Front-End Controller"]
    end

    GRS <-->|"ZMQ Req/Rep + Pub/Sub"| MGM
    TCGen --> GRS
    GP --> GRS
    MGM <-->|"ZMQ"| Dec
    MGM <-->|"ZMQ"| TCS
    MGM <-->|"ZMQ Pub/Sub + Req/Rep"| SS
    MGM --> PG
    Dec --> PG
    IQ --> FFT
    IQ --> Dem --> SW
    MGM --> Freq --> IQ
    MGM --> Rotor
```

## Responsabilidades do MGM8

| Domínio | Responsabilidade |
|---------|------------------|
| **Comunicação** | Receber comandos do GRS Manager, encaminhar ao Station Server, traduzir protocolos, detectar falhas e reconectar |
| **Agendamento** | Passagens de satélite, transmissões de TC, execução automática, detecção de conflitos |
| **Operação autônoma** | Detectar passagens, iniciar pipeline RF, acionar TCs, registrar eventos, recuperar de falhas |
| **Registro** | Logs de sistema, eventos operacionais, auditoria de configuração |
| **Persistência** | Estado da estação, agendamentos, histórico de conexões e comandos no PostgreSQL |
| **Monitoramento** | Integridade dos aplicativos conectados; publicação de estado para o GRS Manager |

## Fronteiras explícitas

**Dentro do escopo do MGM8:**
- Orquestração e estado operacional da estação
- Roteamento de mensagens entre GRS Manager ↔ Station Server
- Agendamento e execução autônoma
- Schema `station_manager` no PostgreSQL

**Fora do escopo (delegado a outros componentes):**
- Processamento RF/IQ, demodulação, FFT → Station Server
- Decodificação de telemetria e armazenamento em hypertables → Decoders + schema `telemetry_stream`
- Metadados de missão e definições de pacotes → schema `mission_control`
- Interface gráfica do operador → GRS Manager
- Predição orbital → GPredict

## Estados operacionais da estação

```mermaid
stateDiagram-v2
    [*] --> Offline
    Offline --> Initializing: startup
    Initializing --> Idle: todos subsistemas OK
    Initializing --> Degraded: subsistema parcial
    Idle --> Manual: operador assume controle
    Idle --> Autonomous: modo autônomo ativo
    Manual --> Idle: operador libera
    Autonomous --> Idle: passagem concluída
    Manual --> PassActive: passagem manual
    Autonomous --> PassActive: passagem detectada
    PassActive --> Idle: fim da passagem
    Degraded --> Idle: recuperação
    Idle --> Offline: shutdown
    Degraded --> Offline: shutdown
```

## Modos de operação

| Modo | Descrição | Gatilho |
|------|-----------|---------|
| **Manual** | Operador controla via GRS Manager | Operador conectado e ativo |
| **Autônomo** | MGM8 executa passagens e TCs agendados | Sem operador ativo + agenda configurada |
| **Degradado** | Operação parcial; subsistemas indisponíveis | Falha detectada em health check |
| **Manutenção** | Bloqueia operações automáticas | Configuração explícita |
