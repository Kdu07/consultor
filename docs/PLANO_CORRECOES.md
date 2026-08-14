# Plano de Correções e Consolidação — Consultor Financeiro Pessoal

> **Para uma sessão futura.** Este documento é autossuficiente: contém o contexto, os
> guardrails invioláveis e os blocos de trabalho prioritizados para resolver o que está
> **faltando**, **errado** ou **desatualizado** no projeto. Foi gerado após uma revisão
> completa do código (2026-06-15). Leia as seções **0 (Contexto)** e **1 (Guardrails)**
> antes de tocar em qualquer arquivo.

---

## 0. Contexto — leia primeiro

**O que é o projeto.** Agente consultor financeiro pessoal, single-user, **local** (roda em
`127.0.0.1:8000`), **estritamente consultivo** (nunca executa ordens, nunca inventa número).
FastAPI + SQLModel/SQLite + SDK `anthropic` com tool-use. Modelo `claude-sonnet-4-6`.
Documento de arquitetura autoritativo: [PLANO.md](PLANO.md). System prompt:
[system_prompt_consultor_otimizado.md](system_prompt_consultor_otimizado.md).

**Estado real do código (importante — diverge da documentação).** As **7 etapas** do PLANO
(Fases 0, 1, 1.5, 2, 3, 4, 5) estão **todas implementadas e funcionando** na working tree.
Os testes passam (`3 passed`). O agente tem **10 tools** ativas no dispatch
([app/agent/loop.py](../app/agent/loop.py)):

`ler_carteira`, `dados_ativo`, `contexto_macro`, `calcular_desvio`, `noticias`,
`importar_extrato`, `gravar_posicoes`, `sugerir_rebalanceamento`, `atualizar_estrategia`,
`proposta_rebalanceamento`.

**O problema central:** o [PLANO.md](PLANO.md) ainda está na **rev. 3**, dizendo que só as
Fases 0–2 foram concluídas e que a Fase 3 é "a próxima". Está ~3 fases atrás da realidade.
Além disso, há **gaps menores conhecidos** (G2, G4, G5, G6) e **trabalho não-commitado**.

**Comandos essenciais (Windows / PowerShell):**
```
# Servidor
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Testes
.venv\Scripts\python.exe -m pytest tests/ -q

# Banco fica em data/carteira.db (sqlite:///data/carteira.db — ver app/config.py)
```

**Decisões já tomadas pelo dono do projeto (não reabrir sem perguntar):**
- **brapi → documentar com gatilho**, NÃO executar agora (Bloco 6).
- **Alvos por ativo (G5) → construir endpoint + UI agora** (Bloco 3).
- **Endurecimento operacional (backup + health Tesouro) → incluir ambos** (Bloco 4).
- Sem prompt caching (PLANO §5 — economia desprezível neste volume).
- Continua em `yfinance` como fonte de RV até o gatilho da brapi.

---

## 1. Guardrails invioláveis (valem para TODO trabalho deste plano)

Estes são os invariantes do projeto. Qualquer mudança que os fira está errada, mesmo que
"funcione".

1. **Antialucinação.** Todo número que chega ao usuário vem de uma tool, com `source` e
   `as_of`. Tool sem dado → retorna `{"error": ...}` e o modelo diz "não tenho esse dado".
   Nunca estimar de memória.
2. **Tools NUNCA lançam exceção para dentro do loop.** Contrato em
   [app/tools/schemas.py](../app/tools/schemas.py): sucesso → dict com dados; falha →
   `{"error": "<motivo>"}`. Toda tool nova DEVE ter o `try/except` que converte exceção em
   `tool_error(...)`. (Ver qualquer tool existente como molde.)
3. **Consultivo, nunca executivo.** Nenhum código ou texto pode dar a impressão de que o
   sistema compra/vende/move dinheiro.
4. **Escrita só após confirmação explícita.** `gravar_posicoes` e `atualizar_estrategia` só
   rodam no turno seguinte ao "sim" do usuário. **Atenção (ver Bloco 1):** para
   `gravar_posicoes` isso é garantido pela arquitetura (o argumento `posicoes` só existe
   após `importar_extrato`); para `atualizar_estrategia` é garantido **apenas pelo prompt**
   (o conteúdo vem do usuário). Não escrever o comentário de forma a confundir os dois.
5. **Marcar dado defasado.** Valor de cache vencido ou de extrato vem com aviso de `as_of`.
6. **Todo dado com `source` + `as_of`.** Schema Pydantic explícito por tool.
7. **`datetime.now(timezone.utc)`** em todo código novo (nunca naive). Padrão do projeto.
8. **Não quebrar o que passa.** Rodar `pytest tests/ -q` antes e depois de cada bloco. Os 3
   testes devem continuar passando. Adicionar testes para código novo quando fizer sentido.
9. **Idempotência de seeds.** Qualquer seed novo em [app/seeds.py](../app/seeds.py) checa
   existência antes de inserir (padrão `_seed_*`).
10. **Local-only.** Nada de auth/HTTPS/expor na rede — o serviço escuta só em `127.0.0.1`.

---

## 2. Ordem de execução e dependências

Faça **na ordem**. Os blocos iniciais protegem trabalho e destravam os seguintes.

| Bloco | O quê | Risco | Depende de |
|---|---|---|---|
| **0** | Commitar Fases 4–5 (proteger trabalho) | nenhum | — |
| **1** | Docs: PLANO.md → rev. 4 + correção do guardrail de estratégia | nenhum | 0 |
| **2** | Limpeza de código morto | baixo | 0 |
| **3** | G5 — alvos por ativo (endpoint + UI) | médio | 0 |
| **4** | Operação — backup testado + health do Tesouro (G6) | baixo | 0 |
| **5** | G2 (retry HTTP) + G4 (nomes do Tesouro) | médio | 0 |
| **6** | brapi como primária — **documentar com gatilho** (não executar) | nenhum | — |

Cada bloco fecha com um commit próprio. Mensagens sugeridas em cada seção.
Lembrete: terminar mensagens de commit com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Bloco 0 — Commitar as Fases 4–5 (URGENTE: proteger trabalho)

**Por quê:** ~11 arquivos das Fases 4 e 5 (rebalanceamento, estratégia, what-if) estão só na
working tree, não-commitados. Um acidente apaga tudo.

**Arquivos envolvidos (referência do estado atual):**
- Novos: `app/tools/rebalanceamento.py`, `app/tools/estrategia.py`, `app/tools/proposta.py`,
  `app/api/rebalanceamento.py`
- Modificados: `app/agent/loop.py`, `app/agent/system_prompt.py`, `app/main.py`,
  `app/seeds.py`, `app/tools/schemas.py`, `static/index.html`,
  `docs/system_prompt_consultor_otimizado.md`

**Passos:**
1. `pytest tests/ -q` — confirmar verde antes.
2. Confirmar que `.env` e `data/*.db` estão no `.gitignore` (não commitar segredo nem banco).
3. Dois commits coesos:
   - **Fase 4:** `rebalanceamento.py` (tool), `api/rebalanceamento.py`, + as partes de
     `loop.py`/`schemas.py`/`system_prompt.py`/`index.html` da Fase 4.
   - **Fase 5:** `estrategia.py`, `proposta.py`, + partes de Fase 5 dos mesmos arquivos +
     `seeds.py` (seed da estratégia).
   - *Se separar ficar custoso* (arquivos misturam Fase 4 e 5), um único commit
     `feat: Fases 4 e 5 — rebalanceamento, estratégia e proposta what-if` é aceitável.

**Critério de pronto:** `git status` limpo (fora deste plano); testes verdes.

---

## Bloco 1 — Documentação: PLANO.md rev. 4 + guardrail de estratégia

**1a. [PLANO.md](PLANO.md) → rev. 4.**
- Cabeçalho (linha ~15): trocar "Fases 0, 1, 1.5 e 2 concluídas. Próximo passo: Fase 3" por
  **"Fases 0–5 concluídas. Pendências: gaps G2/G4 + endurecimento operacional + transição
  brapi (ver PLANO_CORRECOES.md)."**
- §13 (Fases de construção): marcar **Fase 3, Fase 4 e Fase 5 como ✅ CONCLUÍDA**, com 1–2
  linhas do que entregou cada uma (espelhar a memória do projeto / este documento).
- §17 (Próximo passo): apontar para este plano (PLANO_CORRECOES.md) em vez de "Fase 3".
- §16 (gaps): manter G2/G4/G5/G6, mas anotar que G5 e G6 estão sendo resolvidos aqui.

**1b. Correção do guardrail de estratégia (precisão conceitual — guardrail #4 acima).**
O comentário em [app/tools/estrategia.py](../app/tools/estrategia.py) (linhas 4–6) diz que a
tool "espelha gravar_posicoes" e que "a arquitetura garante". **Não garante** — o conteúdo
da estratégia vem do usuário, não de uma read-tool, então só o **prompt** segura. Ajustar o
comentário para deixar isso explícito (algo como: *"A separação proposta→confirmação é
garantida pelo PROMPT (guardrail 9 do system prompt), não pela arquitetura — diferente de
gravar_posicoes, cujo argumento só existe após importar_extrato."*). Não muda
comportamento; corrige a documentação interna.

**Critério de pronto:** PLANO.md não menciona mais "Fase 3 é a próxima"; comentário de
`estrategia.py` reflete a realidade do guardrail.
**Commit:** `docs: PLANO rev.4 (Fases 4-5 concluídas) + corrigir nota de guardrail da estratégia`

---

## Bloco 2 — Limpeza de código morto

Três pontos, todos cosméticos e sem risco (mas confirmar com testes):

1. **[app/agent/loop.py](../app/agent/loop.py) (~linha 182):** no ramo `max_tokens`,
   `partial = _extract_text(response.content)` é atribuído e nunca usado. Remover a linha.
2. **[app/tools/desvio.py](../app/tools/desvio.py) (~linha 84):**
   `pos_extrato = [p for p in posicoes if p not in pos_ao_vivo]` é computado e nunca usado
   (e `not in` sobre objetos SQLModel é O(n²) à toa). Remover.
3. **[app/tools/proposta.py](../app/tools/proposta.py) (~linhas 124–128):** no ramo
   `vender`, quando a venda excede a posição, `valor_op` é ajustado mas o log ainda imprime
   `{qtde:g}x` original → mensagem inconsistente. Ou recalcular a quantidade efetiva para o
   log, ou trocar o texto para refletir o valor ajustado. (Só o log; cálculo está correto.)

**Critério de pronto:** `pytest tests/ -q` verde; nenhuma variável morta nesses três pontos.
**Commit:** `refactor: remover código morto (loop, desvio) e corrigir log da proposta`

---

## Bloco 3 — G5: alvos por ativo (endpoint + UI)

**Contexto.** O modelo [AlvoAtivo](../app/models/alvo.py) (`identificador`, `percentual`,
`notas`) existe e [calcular_desvio](../app/tools/desvio.py) já consome alvos por ativo — mas
**não há como cadastrá-los**. Sem registros, o desvio por ativo sai nulo e
`sugerir_rebalanceamento` ignora o nível de ativo. Decisão do dono: **construir a ferramenta
agora** (os números ele define depois).

**Espelhar o padrão de [app/api/posicoes.py](../app/api/posicoes.py).** Criar
`app/api/alvos.py` com:
- `GET /alvos-ativo` → lista `AlvoAtivo`.
- `POST /alvos-ativo` → upsert por `identificador` (uppercase, como em desvio.py:
  `alvos_ativo[a.identificador.upper()]`). Validar `0 <= percentual <= 100`.
- `DELETE /alvos-ativo/{id}` → remove.
- *(Opcional, mesmo arquivo)* endpoints equivalentes para `AlvoClasse` se quiser editar
  alvos de classe pela UI também — hoje só vêm do seed. Avaliar; não obrigatório.

**Validação importante (PLANO §8.1):** a soma dos alvos por ativo deveria fechar ~100%, e
ser consistente com os alvos por classe. **Regra do PLANO: avisar, não impedir.** Então o
endpoint **não rejeita** soma ≠ 100; retorna a soma atual no response (ex.:
`{"soma_percentual": 92.0, "aviso": "soma diferente de 100%"}`) para a UI exibir. Não travar.

**Registrar o router** em [app/main.py](../app/main.py) (`app.include_router(...)`), seguindo
os outros.

**UI.** Em [static/index.html](../static/index.html), na aba "Carteira", adicionar uma seção
"Alvos por ativo" (espelhar o visual da tabela de posições): listar, adicionar
(identificador + %), remover. Mostrar a soma e o aviso quando ≠ 100%.

**Guardrails específicos:** este endpoint é REST puro para a UI (não passa pelo agente) —
ok, é configuração do usuário, não número de mercado. Não envolve o loop nem guardrail de
confirmação (não é dado de mercado nem escrita disparada pelo modelo).

**Critério de pronto:** dá para cadastrar/editar/remover alvos por ativo pela UI; após
cadastrar, `calcular_desvio` passa a retornar desvio por ativo (testar com a carteira real);
soma ≠ 100% gera aviso, não erro.
**Commit:** `feat: G5 — endpoint e UI para alvos por ativo (POST/GET/DELETE /alvos-ativo)`

---

## Bloco 4 — Operação: backup testado + health do Tesouro (G6)

**4a. Backup do SQLite (PLANO §4.3 — previsto, nunca implementado).**
O banco (`data/carteira.db`) é toda a carteira. "Backup não testado não é backup."
- Criar `scripts/backup.py` (ou `.ps1`) que faz `sqlite3 ... ".backup ..."` **(não copiar o
  arquivo cru — `.backup` é o método seguro com o banco em uso)** para
  `backups/carteira-YYYY-MM-DD.db`. Em Python dá para usar `sqlite3` stdlib:
  `con.backup(dest_con)`.
- Apontar (ou documentar como apontar) a pasta `backups/` para uma pasta de nuvem que o dono
  já use (Drive/Dropbox) — off-site sem custo.
- Reter ~30 dias (apagar backups mais antigos).
- **Testar o restore uma vez** e registrar no `README.md` como restaurar.
- Garantir `backups/` no `.gitignore`.

**4b. Health-check do Tesouro (G6).**
Em [app/api/health.py](../app/api/health.py), adicionar `_check_tesouro()` espelhando
`_check_bcb`/`_check_yfinance`: fazer uma chamada real ao provider do Tesouro
(`app/providers/tesouro_provider.py`) para um título conhecido e reportar `{ok, ...}`.
Incluir no dict `checks` e no cálculo de `all_ok`.

**Critério de pronto:** `scripts/backup.py` roda e gera um arquivo restaurável (restore
testado e documentado no README); `GET /health` mostra o status do Tesouro junto de
db/bcb/yfinance.
**Commit:** `feat: backup testado do SQLite + health-check do Tesouro (G6)`

---

## Bloco 5 — G2 (retry HTTP) + G4 (nomes do Tesouro)

**5a. G2 — 1 retry nas chamadas de rede (PLANO §11).**
Hoje só há timeout. Adicionar **1 retry** (com pequeno backoff) nas chamadas `httpx` de:
- BCB (macro) — `app/tools/macro.py`
- Tesouro provider — `app/providers/tesouro_provider.py`
- (notícias RSS, se aplicável — `app/tools/noticias.py`)

Manter a cadeia de degradação intacta: **falha → fallback (se houver) → cache stale → "não
tenho esse dado"** (guardrail #1 e #2). O retry é uma camada **antes** do fallback, não no
lugar dele. Não introduzir exceção que vaze para o loop.

**5b. G4 — robustez dos nomes do Tesouro. ✅ RESOLVIDO em 08/2026 — não refazer.**
> A migração do import para XLSX ([PLANO_XLSX.md](PLANO_XLSX.md), Bloco 6b) resolveu isto:
> o extrato traz o **vencimento exato**, e o `TesouroProvider` passou a casar por
> **(tipo, ano)** em vez de heurística de texto (`tests/test_tesouro_matching.py`).
> O texto abaixo fica como registro do problema original.
>
> **Atenção — gap novo (G7):** o endpoint público do Tesouro passou a responder **403**,
> então hoje nenhum título recebe preço ao vivo (cai para o saldo do extrato, como previsto).
> Isso é fonte fora do ar, não casamento de nome. Ver §16 do PLANO.md.

O parser BTG gera nomes como `"Tesouro Selic 2028"` e os usa como `ticker`
([app/tools/btg_parser.py](../app/tools/btg_parser.py) seta `ticker=nome` para Tesouro). O
`TesouroProvider` precisa casar esse nome com o título no endpoint do Tesouro. Hoje, se não
casar, cai para o extrato (funciona, mas perde o preço diário oficial — a vantagem da §6.7).
- Implementar **busca tolerante** no `TesouroProvider`: normalizar (maiúsculas/minúsculas,
  acentos, "IPCA+" vs "IPCA", espaços) e casar por (tipo + ano).
- **Validar com um import real** e confirmar que os 5 títulos Tesouro do extrato de exemplo
  recebem preço ao vivo (source `tesouro`), não caem para extrato.
- Se um título não casar, manter o fallback para extrato **com log de warning** (não falhar).

**Critério de pronto:** uma queda transitória de rede não derruba a tool (retry absorve);
após import real, os títulos do Tesouro aparecem com `source=tesouro` no `calcular_desvio`.
**Commit:** `fix: G2 retry HTTP (BCB/Tesouro) + G4 casamento tolerante de nomes do Tesouro`

---

## Bloco 6 — brapi como primária: DOCUMENTAR com gatilho (NÃO executar)

**Decisão do dono:** não contratar/migrar agora. Apenas deixar o **procedimento pronto** e
o **gatilho claro**, para a migração ser trivial quando ele decidir.

**O gatilho (escrever explícito no PLANO §13 / §6.2):**
> Migrar para a brapi **quando você passar a tomar decisões reais de dinheiro com base nos
> números do consultor** — não antes. Pagar ~R$50/mês para *validar* é desperdício; mas
> confiar no yfinance (fonte não-oficial) para embasar um rebalanceamento de verdade é o
> risco que o próprio PLANO mais teme. O gatilho é o uso, não uma data.

**Procedimento de migração (documentar — a infra já existe):**
1. Contratar a brapi (plano Startup; confirmar preço vigente).
2. Preencher `BRAPI_TOKEN` no `.env`.
3. Trocar `price_provider` de `"yfinance"` para `"brapi"` (em `.env` ou
   [app/config.py](../app/config.py)). O `build_rv_provider` em
   `app/providers/composite.py` passa a usar `BrapiProvider` como primário, yfinance recua
   para fallback. **É troca de config, não reescrita** — a abstração `PriceProvider` já
   está pronta.
4. Validar: `GET /health` (idealmente adicionar `_check_brapi` junto ao G6 do Bloco 4) +
   uma cotação real aparecendo com `source=brapi`.
5. Atualizar o custo-base no PLANO §14 (passa de ~R$5–30 para ~R$55–80/mês).

**Critério de pronto:** PLANO.md tem a seção de gatilho e o passo-a-passo; **nada é
executado** (continua em yfinance). `BrapiProvider` permanece como está
(`app/providers/brapi_provider.py`).
**Commit:** `docs: documentar gatilho e procedimento de migração para brapi`

---

## 3. Checklist final (ao terminar todos os blocos)

- [ ] `git status` limpo, cada bloco em seu commit.
- [ ] `pytest tests/ -q` verde.
- [ ] Servidor sobe e `GET /health` mostra db/bcb/yfinance/**tesouro** ok.
- [ ] Dá para cadastrar alvos por ativo pela UI e o desvio por ativo passa a aparecer.
- [ ] `scripts/backup.py` gera backup restaurável; restore testado e documentado no README.
- [ ] PLANO.md (rev. 4) reflete Fases 0–5 concluídas e aponta para este plano.
- [ ] Atualizar a memória do projeto
      (`memory/project_consultor_fase0.md` / `MEMORY.md`) com o novo estado.

## 4. O que está fora deste plano (não fazer sem nova decisão)

- Executar a migração brapi (só documentar — Bloco 6).
- Prompt caching (decisão PLANO §5: desligado).
- Agendador de alertas/resumo automático (PLANO §12: uso sob demanda, sem agendador).
- Acesso fora do PC / mobile / auth / HTTPS (PLANO: local-only).
- Novas features além do escopo das 5 fases — o projeto está funcionalmente completo;
  o foco aqui é consolidar e fechar gaps, não expandir.

---

## 5. Pontos onde PERGUNTAR ao dono antes de decidir

- **Bloco 3:** incluir também edição de **alvos por classe** pela UI (hoje só via seed)?
  É opcional; decidir com o dono se vale o esforço.
- **Bloco 4:** qual pasta de nuvem usar para o off-site do backup (Drive/Dropbox/outro)?
- **Bloco 5b (G4):** se o casamento de nomes do Tesouro exigir um mapa manual de títulos,
  confirmar a lista de títulos que o dono realmente possui antes de hard-codar.
- Qualquer situação em que cumprir um bloco exigir ferir um guardrail da §1 — **pare e
  pergunte**, não contorne o guardrail.
