# ARQUIVADO EM 2026-09-11 — não trabalhe neste repositório

A estação foi dividida em repositórios, um por bloco, na organização
`nanosat-gs`. **Mudanças vão para lá**, não para cá:

- orquestrador (compose, bootstrap, docs, e2e): `nanosat-gs/grs-station`;
- blocos: `nanosat-gs/spacelab-tracking`, `grs-station-manager`,
  `grs-manager`, `grs-tc-scheduler`; o TC Generator segue no fork
  `edsoncepedi/grs-tc-generator`.

A estação roda do clone do orquestrador (`C:/dev/spacelab/grs-station` na
máquina do Edson), cujo `CLAUDE.md` tem a arquitetura atual.

**Não rode `docker compose` aqui.** Este compose usa o mesmo nome de projeto e
de containers do orquestrador; um `up` aqui substituiria a estação que está
rodando pelas imagens antigas. Só em rollback — ver `ARCHIVED.md`.

Tudo abaixo é o registro histórico de como a estação era antes da divisão, e
não descreve mais o sistema (por exemplo: o painel já não lê o banco, e o TC
Scheduler tem uma API na 5591).

---

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
| **GRS Manager** | `src/grs_manager/` | Painel do operador (rotor + satélites) e ponte rotctld para controle manual |
| **Satellite Tracker** | `libs/spacelab-tracking/` | Biblioteca: SGP4, CelesTrak, previsão de passagens |
| **Rotor Manager** | `src/mgm8/vendor/` (cópia, ver `UPSTREAM.md`) | Protocolo Rot2Prog, hardware |

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
| GRS Manager (rotctld / painel) | 4533 / 5590 |
| Station Manager (ZMQ REP) | 5580 |
| TC Scheduler | — |

Links, credenciais de desenvolvimento e endpoints em `docs/acessos.md`. A
confusão mais comum é abrir a 4533 (rotctld, protocolo hamlib) esperando o
painel, que está na 5590.

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
qualquer automação. O servidor rotctld continua de pé na 4533 para quem quiser
assumir a antena por um cliente hamlib, mas o painel não reporta mais essa
conexão: destacá-la sugeriria que ela ainda faz parte do fluxo normal.

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
O painel do GRS Manager **lê** o banco (`status/station_data.py`), e só lê — a
única escrita dele é no cache de TLE, que é outro recurso.

**O painel do GRS Manager degrada em vez de falhar.** Sem `PG_DATABASE_URL`, ou
com o Postgres fora do ar, ele volta a ser só o controle de rotor. Uma passagem
em andamento não pode parar porque o banco caiu.

**O fim da janela marca os telecomandos como `sent`.** Isso afirma mais do que a
estação observa: ela sabe que rastreou a passagem, não que o rádio transmitiu —
não há encoder nem modulador. Foi decisão do operador, ciente do limite, porque
sem isso um comando ficava em `queued` para sempre e a fila de pendentes nunca
esvaziava. Cada marcação grava um `execution_logs` dizendo que veio do fim da
janela e não de confirmação (`db.SENT_BY_PASS_COMPLETION`); quando os fluxos de
dados existirem, um `sent` com evidência será distinguível destes pela mensagem.
Só passagem `completed` marca `sent` — a `missed` devolve os comandos à fila,
porque ali a antena nem chegou a apontar.

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
- **`.panel` nasce `display: none` no `mission-control.css`.** Lá ele é aba de
  dashboard e espera um `.active` que o JS atribui. Uma página sem abas que
  reuse a classe precisa redeclarar `display: block`, senão o conteúdo é
  renderizado e não aparece — foi o que escondeu `/satellites` por inteiro.
- **Satélite sem telecomando à espera não entra no plano.** `fetch_trackable_
  satellites` usa `JOIN telecommands`, não `LEFT JOIN`: sem nada a transmitir
  não há o que agendar. Ele continua aparecendo no painel com posição, porque a
  posição corrente vem de outra consulta, sem esse filtro. Cadastrar um
  satélite e estranhar que não há passagem planejada costuma ser isto.
- **O plano ignora passagens rasantes.** `is_worth_tracking` corta abaixo de
  `SCHEDULER_MIN_PASS_ELEVATION_DEG` (5°) ou 60 s. Um cliente com máscara em 0°
  vai listar passagens que a estação decidiu não rastrear — é diferença de
  política, não de cálculo.
- **Divergência com outro software de tracking é quase sempre o TLE.** Antes de
  suspeitar da geometria, compare o epoch dos dois lados: um gpredict que nunca
  rodou "Update TLE data" pode estar meses atrás, e meses de erro along-track
  põem o satélite a milhares de quilômetros do lugar certo. O ponto subsatélite
  é o teste decisivo, porque não depende de onde a estação está.
- **O card do satélite no painel atrasa até ~45 s.** Ele lê
  `satellite_tracking_status` (escrito a cada 30 s) e a página busca a cada
  15 s, enquanto o rotor vem ao vivo. Durante uma passagem o satélite varre
  ~0,3°/s, então os dois números divergem em graus — o do rotor é o atual.

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
de satélites com validação no CelesTrak; painel do operador no GRS Manager
(grade de satélites, modal com vetor de estado e agendamentos, botão de
revalidar TLE).

Em aberto: encoders/moduladores (transmissão real) — enquanto não existirem, o
`sent` do fim da janela é inferência, não confirmação; estreitar a janela de
rastreamento para o período de fluxo de dados; mapa de trajetória no painel;
PR para o upstream do fix dos GRANTs e do `.panel` da página de satélites.
