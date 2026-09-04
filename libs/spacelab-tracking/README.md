# spacelab-tracking

Propagação orbital (SGP4) e previsão de passagens para a estação terrestre
SpaceLab. Substitui o gpredict como fonte de apontamento: ao contrário dele,
esta biblioteca é consumível por código, o que é o que torna a operação
autônoma possível.

Usada por dois consumidores com necessidades diferentes:

- **Station Manager** (`mgm8`) — az/el instantâneo, a cada tick do laço de
  apontamento durante uma passagem.
- **TC Scheduler** — previsão de passagens (AOS/LOS/culminação) no horizonte de
  planejamento, para decidir qual satélite rastrear.

## Módulos

| Módulo | Papel |
|---|---|
| `celestrak` | Obtenção de dados orbitais (OMM/JSON com fallback para TLE) e cache local |
| `propagation` | Constrói o `Satrec` do SGP4 e propaga; agnóstico à origem dos dados |
| `coordinates` | TEME → ECEF → geodésica, e ECEF → topocêntrico (azimute/elevação) |
| `tracking` | Junta tudo: posição atual e previsão de passagens |
| `config` | Estação terrestre e cache, configuráveis por variável de ambiente |
| `cli` | Ferramenta de linha de comando para depuração e validação |

## Configuração

Tudo por variável de ambiente, sem editar código:

| Variável | Default | O que é |
|---|---|---|
| `GS_NAME` | `Estação de Teste` | Nome da estação |
| `GS_LATITUDE_DEG` | `-23.5505` | Latitude do observador |
| `GS_LONGITUDE_DEG` | `-46.6333` | Longitude do observador |
| `GS_ALTITUDE_M` | `760.0` | Altitude em metros |
| `GS_MIN_ELEVATION_DEG` | `0.0` | Máscara de elevação (abaixo disso, sem visada útil) |
| `TRACKING_DATA_DIR` | `./data` | Onde fica o cache de dados orbitais |
| `TRACKING_CACHE_MAX_AGE_MINUTES` | `15` | Idade máxima do cache antes de rebuscar. `TRACKING_CACHE_MAX_AGE_HOURS` ainda é aceita e convertida. |
| `TRACKING_HTTP_TIMEOUT_SECONDS` | `10` | Timeout das chamadas ao CelesTrak |

Os defaults de latitude/longitude são um **exemplo** (São Paulo) e precisam ser
trocados pelos da estação real.

## Doppler

`get_tracking_info()` também devolve `range_rate_km_s` — a taxa de variação da
distância estação→satélite (negativa enquanto se aproxima), calculada a partir
da velocidade convertida para o referencial girante ECEF (rotação GMST mais o
termo `-ω × r`). A partir dela, para uma portadora emitida pelo satélite:

```python
info = get_tracking_info(satrec, name, station=station)
info.doppler_shift_hz(437_000_000)        # desvio visto na estação (Hz)
info.observed_frequency_hz(437_000_000)   # frequência já corrigida p/ sintonizar
```

O sinal segue a convenção física: satélite se aproximando → `range_rate` < 0 →
desvio positivo. Para a ISS em 70 cm, o desvio fica abaixo de ~11 kHz e passa
por zero na culminação.

## Validação

A melhor checagem do cálculo é comparar com uma ferramenta independente usando
exatamente os mesmos elementos orbitais:

```bash
python -m spacelab_tracking.cli --norad-id 25544 --next-pass
python -m spacelab_tracking.cli --norad-id 25544 --export-tle iss.tle
```

Importe `iss.tle` no Gpredict (Edit > Update TLE > From files) e compare AOS,
LOS e elevação máxima. Divergências de segundos são esperadas (o refinamento
numérico difere); divergências de minutos indicam erro real.

## Precisão

A rotação TEME→ECEF usa apenas o GMST, ignorando movimento do polo e correções
de nutação/precessão de curtíssimo prazo. O erro residual é da ordem de metros —
desprezível frente à incerteza do próprio TLE/SGP4, que é de 1 a alguns km.
