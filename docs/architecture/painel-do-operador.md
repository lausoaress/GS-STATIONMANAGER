# Painel do operador — o que é e por quê

> Leitura acessível. Cobre a mudança feita em `src/grs_manager/status/`.

## O que mudou

O painel do operador passou a ter **uma interface só** — o dashboard do
**Station Manager** (tema escuro, cabeçalho SpaceLab, abas). Ele é servido pelo
GRS Manager e **consome os dados que o GRS Manager já lia do banco**.

Antes existiam dois "fronts" concorrendo:

- o painel do GRS Manager (`grs_manager/status/`), montado como HTML dentro de
  Python — funcional, mas visualmente à parte;
- o dashboard do Station Manager (identidade e layout definidos pela Laura).

A partir daqui o dashboard do Station Manager é **o** painel, e o HTML embutido
no Python (`_render_page`, `_PAGE_CSS`, `_PAGE_JS`) foi removido.

## O que foi mantido e o que foi trocado

| Parte | Situação |
|---|---|
| `station_data.py` — leitura do plano da estação (satélites, posição, passagens, TCs, histórico 24 h) no Postgres | **mantida** — é a camada de dados, e é boa |
| Endpoints `/api/station`, `/api/satellite/<code>`, `/api/tle/refresh`, `/events` (SSE do rotor) | **mantidos** sem mudança |
| A *view* (HTML/CSS/JS) | **trocada** por `templates/index.html` no visual do Station Manager |
| Regra "o GRS Manager não escreve no banco" | **mantida** — criar/editar TC continua sendo link para o TC Generator |

## O que o painel mostra

- **Cabeçalho**: rotor ao vivo (az/el via SSE, chip verde/vermelho) + botão
  "Atualizar TLE".
- **Aba Satélites**: um card por satélite com azimute, elevação, distância e
  contagem regressiva para o próximo AOS/LOS. Satélite sem dado orbital aparece
  como "não rastreável".
- **Aba Passagens**: tabela achatada com a próxima passagem de cada satélite
  (AOS, LOS, elevação máxima, nº de TCs, situação).
- **Modal de detalhe** (clicando num satélite): vetor de estado ECI/TEME, ponto
  subsatélite (geodésica), coordenadas da estação, apontamento atual, e as abas
  **Agendamento** / **Histórico (24 h)** com os telecomandos de cada passagem
  separados entre "a enviar" e "enviados".

## Sem banco

Se o `PG_DATABASE_URL` não estiver definido (ou o Postgres cair), o painel volta
a ser só o controle do rotor — as abas de satélites mostram um aviso, e o
cabeçalho continua funcionando. O rotor é a razão de existir da página; o resto
é adição.

## O que ainda é do TC Generator

Criar telecomando, editar, aprovar, e a página de cadastro de satélites
(`/satellites`) continuam no TC Generator — o painel só aponta para lá. Ver
[tc-followup-frame-e-aprovacao.md](tc-followup-frame-e-aprovacao.md) para o que
falta levar para lá (validação de frame e workflow de aprovação).
