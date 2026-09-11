# Arquivado em 2026-09-11

**A estação terrestre não vive mais neste repositório.** Cada bloco do diagrama
passou a ter o seu repositório próprio, na organização
[`nanosat-gs`](https://github.com/nanosat-gs), e eles conversam só pela rede
(ZMQ e HTTP).

| Bloco | Era aqui | Agora |
|---|---|---|
| Satellite Tracker (biblioteca) | `libs/spacelab-tracking/` | [nanosat-gs/spacelab-tracking](https://github.com/nanosat-gs/spacelab-tracking) |
| Station Manager | `src/mgm8/` | [nanosat-gs/grs-station-manager](https://github.com/nanosat-gs/grs-station-manager) |
| GRS Manager | `src/grs_manager/` | [nanosat-gs/grs-manager](https://github.com/nanosat-gs/grs-manager) |
| TC Scheduler | `src/tc_scheduler/` | [nanosat-gs/grs-tc-scheduler](https://github.com/nanosat-gs/grs-tc-scheduler) |
| Compose, docs, teste ponta a ponta | raiz, `docs/`, `tests/` | [nanosat-gs/grs-station](https://github.com/nanosat-gs/grs-station) (orquestrador) |
| TC Generator | `services/grs-tc-generator/` (submódulo) | [edsoncepedi/grs-tc-generator](https://github.com/edsoncepedi/grs-tc-generator) — continua no fork |

A história foi preservada: cada repositório novo foi extraído deste com
`git filter-repo`, então `git log` e `git blame` continuam contando quem fez o
quê. Um exemplo: o `station_data.py`, que mudou do GRS Manager para o TC
Scheduler, carrega os commits desde quando nasceu no painel.

Para subir a estação:

```powershell
git clone https://github.com/nanosat-gs/grs-station.git
cd grs-station
.\bootstrap.ps1
cp .env.example .env
docker compose up -d --build
```

## O que mudou no caminho

- O painel do GRS Manager **não lê mais o banco**. Ele pergunta ao TC
  Scheduler, que ganhou uma API de leitura na porta 5591. O banco tem um dono
  só: quem escreve é quem serve.
- O Rotor Manager, que era submódulo, virou uma cópia dentro do Station
  Manager (`src/mgm8/vendor/`, com `UPSTREAM.md` registrando origem e commit).
- O agendamento em memória do `mgm8` (`api/`, `pass_scheduler.py`), que nenhum
  processo subia, foi removido.

## As branches da Laura

- `feat/painel-unico-laura` — **incorporada inteira** (painel único com a
  identidade do dashboard do Station Manager, e o Doppler na biblioteca de
  tracking). Está nos repositórios novos.
- `main` (`4795fc5`) e `laura/propagator-tc-prototype` — **ficaram de fora de
  propósito**. São a linha antiga: o dashboard em cima do agendamento em
  memória, e um protótipo que a própria mensagem de commit marca como a ser
  substituído. Continuam aqui, intocadas.

## Não rode `docker compose` aqui

O compose deste repositório e o do orquestrador usam o **mesmo nome de
projeto** (`gs-stationmanager`) e os **mesmos nomes de container**. Isso foi
de propósito, para o orquestrador herdar os volumes com os dados. A
consequência é que um `docker compose up` aqui **substitui a estação que está
rodando** pelas imagens antigas.

A única razão para rodá-lo é um **rollback**: `docker compose down` no
orquestrador (nunca com `-v`, que apaga os volumes) e `docker compose up -d`
aqui.

Nada foi apagado deste repositório: esta branch é o registro de como a estação
era antes da divisão.
