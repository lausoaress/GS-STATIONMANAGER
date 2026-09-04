# Follow-up: validação de frame e aprovação de telecomando

> Especificação para um **PR separado ao fork `edsoncepedi/grs-tc-generator`**.
> Estas duas peças vieram do protótipo (`laura/propagator-tc-prototype`) mas não
> cabem no `GS-STATIONMANAGER`: o telecomando é criado e persistido no TC
> Generator, e o GRS Manager/Station Manager não escrevem naquele banco.

## Por que não entra aqui

- O `tc_scheduler` lê a tabela `telecommands` do banco do TC Generator (SQL
  puro, `src/tc_scheduler/db.py`). Ele **não** tem coluna de frame nem de
  aprovação para checar.
- O painel do GRS Manager é somente-leitura sobre esse banco — a arquitetura
  reserva a escrita ao TC Scheduler (plano de passagens) e ao TC Generator
  (definição dos comandos).

## 1. Validação de frame opaco

**Onde**: no TC Generator, na criação/edição do telecomando.

**O quê**: se o operador informar o frame já codificado (campo novo,
sugestão `frame_hex TEXT`), validar **só a estrutura**, nunca a semântica:

- normalizar: remover espaços e `:`, minúsculas;
- número par de dígitos hexadecimais;
- `bytes.fromhex()` não pode falhar;
- tamanho ≤ 4096 bytes (`MAX_FRAME_BYTES`).

Referência de implementação: `_normalize_frame_hex` em
`src/mgm8/application/tc_scheduler.py` no branch `laura/propagator-tc-prototype`.

O MGM8/Scheduler continuam tratando o frame como bytes opacos — quem entende o
conteúdo é o TC Generator (definição do pacote) e, na transmissão, os encoders.

## 2. Workflow de aprovação

**Onde**: no TC Generator (colunas + tela) e no `tc_scheduler` (respeitar a
flag na seleção).

**Colunas** (tabela `telecommands`):

| Coluna | Tipo | Uso |
|---|---|---|
| `requires_approval` | `BOOLEAN NOT NULL DEFAULT FALSE` | comando sensível |
| `approved_by` | `VARCHAR(128)` | quem aprovou |
| `approved_at` | `TIMESTAMPTZ` | quando |

**Regra**: um telecomando com `requires_approval = TRUE` e `approved_at IS NULL`
**não entra no plano**. No `tc_scheduler/db.py`, adicionar à condição
`_NEEDS_A_PASS` / à query de satélites rastreáveis:

```sql
AND (t.requires_approval = FALSE OR t.approved_at IS NOT NULL)
```

**Ação de aprovar**: botão na tela do TC Generator (é quem tem sessão de
operador e escrita no banco). O painel do GRS Manager pode, no máximo, *mostrar*
"aguardando aprovação" — não aprovar.

Referência: `ScheduledTelecommand.approve()` e `list_pending_approval()` em
`src/mgm8/application/tc_scheduler.py` no branch do protótipo.

## Ordem sugerida

1. Migração do schema (`frame_hex`, `requires_approval`, `approved_by`, `approved_at`).
2. Validação de frame na criação (rejeita cedo, mensagem clara).
3. Guard no `tc_scheduler` (uma linha na query) — pode ir junto num PR a este repo.
4. Tela de aprovação no TC Generator.
