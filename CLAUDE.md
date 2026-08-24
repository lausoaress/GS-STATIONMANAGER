# Contexto do projeto

Estação terrestre do SpaceLab. Este repositório é o **orquestrador**: o
`docker-compose.yml` da raiz sobe a estação inteira, e os outros blocos entram
como submódulos em `services/`.

## Os blocos e onde eles vivem

| Bloco | Onde | O que faz |
|---|---|---|
| **TC Generator** | `services/grs-tc-generator/` (submódulo) | Interface web: operador cria telecomandos e cadastra satélites |
| **TC Scheduler** | `src/tc_scheduler/` | Decide o que rastrear e quando |
| **Station Manager** | `src/mgm8/` | Controla o rotor; rastreia um satélite sozinho durante a passagem |
| **GRS Manager** | `src/grs_manager/` | Ponte rotctld: é aqui que o gpredict conecta (caminho manual) |
| **Satellite Tracker** | `libs/spacelab-tracking/` | Biblioteca: SGP4, CelesTrak, previsão de passagens |
| **Rotor Manager** | `vendor/grs-rotor-manager/` (submódulo) | Protocolo Rot2Prog, hardware |

## Permissões dos repositórios

Nenhum destes repos é do Edson. Isso restringe o que é possível:

- `lausoaress/GS-STATIONMANAGER` — **escrita na branch `dev_edson`** (a `main` é da Laura Soares).
- `spacelab-ufsc/grs-tc-generator` — **somente leitura** (push dá 403). O trabalho vai para o fork `edsoncepedi/grs-tc-generator`, que é o que o submódulo aponta. Levar algo para o upstream exige pull request.
- `spacelab-ufsc/grs-rotor-manager` — somente leitura, vendorizado.

`main == origin/main` num clone **não** prova acesso de escrita. Confirme com
`git push --dry-run` antes de assumir.

Mudança no TC Generator: commit no submódulo → push para o fork → commit do
ponteiro do submódulo aqui.

## Como rodar

```powershell
git submodule update --init --recursive
cp .env.example .env
docker compose up -d --build
```

| Serviço | Porta |
|---|---|
| TC Generator (web) | 5000 |
| pgAdmin | 5050 |
| PostgreSQL | 5432 |
| GRS Manager (rotctld / status) | 4533 / 5590 |
| Station Manager (ZMQ REP) | 5580 |
| TC Scheduler | — |

Observar o fluxo:
```powershell
docker compose exec tc-scheduler python -m tc_scheduler.monitor --watch
docker compose exec tc-scheduler python tools/station_demo.py prepare --code SAT-001 --norad-id 44885
docker compose exec tc-scheduler python tools/station_demo.py simulate-pass --code SAT-001
```

Testes: `pytest` na raiz (cobre `tests/` e `libs/spacelab-tracking/tests/`).

## Decisões de arquitetura, e por quê

**O gpredict foi substituído por tracking próprio.** Ele calcula bem, mas só
através da interface gráfica — não aceita controle programático, o que impedia
qualquer automação. O caminho manual (gpredict → GRS Manager → rotctld)
continua funcionando em paralelo.

**O laço de apontamento em tempo real roda no Station Manager, não no
Scheduler.** Planejar é lento (propagar 24h de N satélites) e apontar é rápido.
Separados, um replanejamento nunca atrasa o rotor, e uma queda do Scheduler no
meio de uma passagem não a interrompe. O Scheduler manda uma ordem por passagem
(`track_satellite`), não um setpoint por segundo.

**A autonomia mora no TC Scheduler.** Ele pontua as passagens por prioridade do
telecomando à espera → quantidade de comandos → elevação máxima, e escolhe as
que não se sobrepõem (a estação tem um rotor só).

**O TC Scheduler é o único que escreve no banco.** O Station Manager fica sem
dependência de Postgres, o que importa se ele um dia rodar na máquina do rádio.

**Nada marca telecomando como `sent`.** Sem os encoders/moduladores não há como
saber se foi transmitido. `queued` diz o que é verdade: tem hora marcada para
sair. Quando os fluxos de dados existirem, o gancho é a tabela
`execution_logs`, que já existe e já tem aba na UI.

**`satellites.norad_id` fica NULL no seed.** Um NORAD ID errado não falha: a
estação simplesmente aponta para outro objeto. Por isso a página `/satellites`
valida contra o CelesTrak antes de salvar.

## Armadilhas conhecidas

- **Duas cópias do TC Generator.** Existe um clone avulso em
  `../grs-tc-generator` além do submódulo. O compose constrói do **submódulo** —
  editar o outro não tem efeito.
- **`docker-entrypoint-initdb.d` só roda em volume vazio.** Mudança de schema
  exige `ALTER TABLE` manual ou `docker compose down -v` (que **apaga** os dados).
- **`--rotor mock` no Docker.** O `RotorManager` vendorizado tem o socket SUB
  fixo em `tcp://localhost:5560`, o que não funciona entre containers. Hardware
  real e simulador continuam fora do Docker.
- **CelesTrak responde 404 com corpo `No GP data found`** para ID inexistente.
  Checar o corpo antes de `raise_for_status`, senão "não existe" (que deve
  bloquear) vira "site fora do ar" (que deve apenas avisar).
- **Coordenadas da estação são um exemplo** (São Paulo) nas variáveis `GS_*`.
  Trocar antes de qualquer uso real.

## Convenções

- Comentários e mensagens de commit em português; código e identificadores em
  inglês. O TC Generator (upstream de terceiros) usa inglês também nos
  comentários — seguir o arquivo em que se está mexendo.
- Arquitetura hexagonal no `mgm8`: portas em `domain/ports.py`, adapters em
  `infrastructure/`, casos de uso em `application/`. A composition root
  (`rotor_zmq/main.py`) é o único módulo que conhece implementações concretas.
- Testes acompanham comportamento, não implementação. Os de geometria em
  `libs/spacelab-tracking/tests/` existem porque testes de consistência interna
  não pegavam um sinal invertido na rotação TEME→ECEF.

## Estado e próximos passos

Feito: orquestração num compose só; biblioteca de tracking; rastreamento
autônomo no Station Manager; TC Scheduler com agendamento; página de cadastro
de satélites com validação no CelesTrak.

Em aberto: encoders/moduladores (transmissão real) e o status dos telecomandos
que depende deles; estreitar a janela de rastreamento para o período de fluxo
de dados; exibir o plano no dashboard; PR do fix dos GRANTs para o upstream.
