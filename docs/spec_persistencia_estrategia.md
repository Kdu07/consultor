# Spec — Persistência de Estratégia de Investimento

> Adições previstas para o PLANO: **§7.3** (modelo de dados), uma **tool de escrita**, um
> **guardrail novo** e **linhas para o system prompt** + campos no contexto dinâmico.
> Princípio-guia: a estratégia é a **âncora** — mutável, mas só por ato **deliberado e
> confirmado**, com freio comportamental em medo/euforia.

## Contexto

Hoje o contexto dinâmico carrega alvos estáticos + perfil + config. Falta a **estratégia
narrativa** (tese) e os **planos de compra/venda futuros** — e um caminho seguro para
alterá-los. Esta spec reaproveita dois padrões que o projeto já tem:

1. **Contexto dinâmico injetado por sessão** → todas as sessões herdam a estratégia, sem
   nada novo de infraestrutura.
2. **Confirmação como fronteira de turno + tool de escrita separada** (como o import) → a
   mudança só grava após "sim" explícito.

## 1. Modelo de dados (adições à §7.3)

### `EstrategiaInvestimento`
- `id: int` (PK)
- `tese: str` — narrativa curta: por que a carteira é assim, intenção de longo prazo.
- `version: int` — incrementa a cada alteração.
- `updated_at: datetime`

Single-user: uma linha "ativa". O versionamento dá rastreio.

### `PlanoFuturo` (filha de `EstrategiaInvestimento`)
- `id: int` (PK)
- `estrategia_id: int` (FK)
- `descricao: str` — ex.: "migrar parte da RF para ações", "levar infra a 20%".
- `gatilho: str | None` — condição/disparo: data ("até dez/2026"), evento ("quando a
  carência do fundo X vencer") ou limiar ("se infra < 15%").
- `horizonte: str | None` — janela pretendida.
- `status: Enum[ativo, cumprido, cancelado]`
- `created_at`, `updated_at: datetime`

### `HistoricoEstrategia` (log de auditoria)
- `id`, `estrategia_id`, `timestamp`, `origem` (ex.: "usuário via chat") + o diff
  (`campo`, `valor_anterior`, `valor_novo`) ou um snapshot JSON por alteração.
- Para quê: rastreio + reversibilidade + um **check comportamental de segundo nível** (ver
  se a "estratégia" vem deslizando para perseguir o mercado).

**Nota de design:** as restrições inegociáveis (dividendos-only, ≥60% líquido > D+6) hoje
moram no **perfil**. Recomendo **mantê-las lá** (perfil = quem o investidor é) e a `tese`
apenas referenciá-las, para não duplicar fonte de verdade. Promover para
`EstrategiaInvestimento` é opção, mas duplica.

## 2. Injeção no contexto dinâmico

A montagem do bloco `=== CONTEXTO DINÂMICO ===` passa a incluir dois campos novos, lidos do
banco a cada sessão:
- `{tese}` → seção **"## Tese da estratégia"**
- `{planos_futuros}` → seção **"## Planos futuros"** (cada `PlanoFuturo` com status `ativo`:
  descrição, gatilho, horizonte)

É isso que faz "todas as sessões seguem a estratégia".

## 3. Tool de escrita: `atualizar_estrategia`

Espelha `gravar_posicoes`: tool **separada, de escrita**, chamada **só no turno de
confirmação**. Fluxo em dois turnos (como o import):

1. Usuário pede a mudança ("quero passar a mirar 20% em infra" / "registra que não pretendo
   aportar por 3 meses"). O agente **reflete de volta** o que entendeu e pergunta "confirma?"
   — o turno encerra (só texto). **Nenhuma escrita aqui.**
2. Usuário confirma ("sim") → o agente chama `atualizar_estrategia(mudancas)` → grava +
   registra em `HistoricoEstrategia`.

Schema (Pydantic) — `mudancas` é um patch explícito:
- `tese: str | None`
- `planos_adicionar: list[PlanoFuturoInput] | None`
- `planos_atualizar: list[{id, campos…}] | None`
- `planos_remover: list[id] | None` (ou marcar `status=cancelado`)
- `alvos: … | None` (se a mudança mexe na alocação-alvo)

Retorno: `{ok, version_nova, resumo_do_que_mudou}` em sucesso; `{error}` em falha (contrato
de tool que **nunca estoura**, §3 do PLANO).

**Leitura:** não precisa de tool separada — a estratégia já vem injetada no contexto. (Se um
dia o contexto crescer, dá para adicionar `ler_estrategia`; no escopo atual é desnecessário.)

## 4. Guardrail novo (guardrail 7 — ou extensão do 4)

> **Nunca alterar a estratégia (tese, planos, alvos, restrições) sem confirmação explícita e
> deliberada**, via a tool de escrita separada `atualizar_estrategia` — espelhando o
> guardrail 4 (import). **Reforço comportamental:** diante de sinais de medo/euforia ou
> reação a movimento de curto prazo, **desacelerar e verificar se é decisão deliberada de
> plano antes de gravar**. Uma mudança de estratégia no susto é exatamente o que a âncora
> existe para impedir. Toda alteração é registrada (`HistoricoEstrategia`) e reversível.

Como o guardrail 4, é garantido pela **arquitetura** (a escrita só existe no turno de
confirmação), não só pelo texto do prompt.

## 5. Linhas para o system prompt (adições ao prompt otimizado)

Encaixam ao lado da seção 7 ("Quando o plano está incompleto") e da seção 12 (resumo):

- **Na âncora (seção 5/6):** "Os **planos futuros** fazem parte da âncora. Você os pesa ao
  analisar, os traz à tona quando relevante (ex.: na cadência mensal, lembrar de um plano
  cujo gatilho/horizonte está chegando) e **sinaliza quando uma ação proposta contradiz um
  plano declarado** — sem decidir pelo usuário."
- **Mudança de estratégia (dentro da seção 7):** "Alterar a estratégia (tese, planos, alvos,
  restrições) é um **ato deliberado e confirmado**: você reflete a mudança, espera o 'sim'
  explícito e só então registra (`atualizar_estrategia`). Em medo/euforia ou reação a curto
  prazo, **desacelere e confirme a intenção de plano antes de gravar**."
- **No resumo (seção 12), novo item:** "**Alterar a estratégia sem confirmação explícita e
  deliberada.** Em medo/euforia, freia antes de gravar."
- **No contexto dinâmico:** adicionar **"## Tese da estratégia"** (`{tese}`) e **"## Planos
  futuros"** (`{planos_futuros}`).

## 6. Onde entra no roadmap

- **Enhancement pós-Fase 2** (depois que import + desvio estiverem confiáveis).
- **Dica de migração:** criar os *stubs* das tabelas (`EstrategiaInvestimento`,
  `PlanoFuturo`, `HistoricoEstrategia`) já no schema da **Fase 0** evita uma migração depois;
  a tool, o guardrail e as linhas do prompt vêm na fase do enhancement.
- Cross-ref: **§13 (Fase 5)** e **§16** do PLANO, atualizados.
