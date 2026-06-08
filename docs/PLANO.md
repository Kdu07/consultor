# Agente Consultor Financeiro Pessoal — Plano Final

> Versão final (rev. 3 — atualizado após conclusão das Fases 0–2). Decisões fechadas:
> **execução local** (roda no PC do usuário, sem servidor, sem mobile, sem PWA);
> **brapi.dev como fonte primária de cotações planejada para produção** (paga, oficial),
> com **yfinance apenas para validação/bootstrap e fallback** — a troca para a brapi é
> prevista, não hipótese; **Tesouro Direto (preço diário oficial)** para a renda fixa
> pública; **Banco Central (API SGS)** para macro e **RSS** para notícias;
> **import de extrato por colagem de texto** (BTG emite apenas PDF — ver §7.1 e §7.4)
> com gravação só após confirmação; **desvio calculado sobre snapshot coerente** com
> divulgação de frescor; **loop do agente** com teto de iterações e tools que nunca
> estouram; **Claude Sonnet 4.6** como modelo, **sem prompt caching** (decisão deliberada
> — ver §5). System prompt já redigido (`system_prompt_consultor_otimizado.md`).
>
> **Estado atual:** Fases 0, 1, 1.5 e 2 concluídas. Próximo passo: Fase 3 (notícias + UI).

---

## 1. Objetivo

Agente de IA pessoal, single-user, **estritamente consultivo**, que funciona como
consultor financeiro: monitora a carteira, dá insights fundamentados em dados reais e
avisa quando algo relevante muda. Roda **localmente** no PC do usuário. **Nunca executa
ordens. Nunca inventa números.**

---

## 2. Princípio central

Um único agente bem instruído com poucas tools confiáveis. A inteligência está em dois
pilares:

1. **Antialucinação:** todo número vem de uma tool, com a fonte e a data marcadas. Sem
   dado → "não tenho esse dado". Nunca estimar de memória. E o agente separa **fato**
   (vem da tool) de **análise** (seu raciocínio, falível) — nunca vende opinião como dado.
2. **System prompt denso** com conhecimento real de alocação, risco, disciplina de longo
   prazo e contrapeso comportamental. Já redigido (ver `system_prompt_consultor_otimizado.md`).

---

## 3. Arquitetura

### Visão geral
- **Frontend:** UI web **local** (HTML/CSS/JS) servida pelo próprio FastAPI, acessada no
  navegador em `http://127.0.0.1:8000` — chat + dashboard da carteira + tela de import de
  extrato. Sem SPA pesado: é single-user local.
- **Backend:** FastAPI (Python), agente via API Anthropic com tool-use.
- **Banco:** SQLite (um arquivo: posições + perfil de risco + alocação-alvo + config de
  rebalanceamento + cache de cotações + histórico mensal).
- **Execução:** local, no PC do usuário. Uvicorn em `127.0.0.1`. Ver seção 4.
- **Modelo:** Claude Sonnet 4.6 (`claude-sonnet-4-6`), pay-as-you-go. Ver seção 5.
- **Dados de mercado:** brapi (cotações, **primário planejado**) com yfinance para
  validação/fallback; Tesouro Direto (preço diário oficial da RF pública); BCB/SGS (macro);
  RSS (notícias). Ver seção 6.

### Decisões de stack
| Item | Escolha | Por quê |
|---|---|---|
| Python | 3.11+ | Estável, bom suporte de libs, type hints maduros |
| Web framework | FastAPI + Uvicorn | Async nativo, ótimo para I/O de rede |
| SDK do modelo | `anthropic` (oficial) | Tool-use de 1ª classe |
| Modelo | claude-sonnet-4-6 | Melhor custo/qualidade para o consultor |
| ORM | SQLModel | Pydantic + SQLAlchemy, pouco boilerplate |
| Validação | Pydantic v2 | Schemas das tools e da confirmação de import |
| Parser de extrato | `re` (regex stdlib) | Import por colagem de texto (PDF) — ver §7.1. `openpyxl`/`pandas` disponíveis se necessário no futuro |
| Cliente HTTP | `httpx` | Async, timeouts, retries |
| Cotações (RV) | `brapi` (primário planejado) → `yfinance` (validação/fallback) | brapi: paga/oficial; yfinance: gratuito, só validação (ver 6) |
| Cotações (RF pública) | API / dado aberto do Tesouro Direto | Preço diário oficial; tira o Tesouro do "datado" (ver 6.7) |
| Macro | API pública do BCB (SGS) | Oficial, gratuita, sem chave |
| Notícias | feeds RSS (InfoMoney/Valor) | Gratuito |
| Gestor de deps | `uv` | Rápido, lockfile reprodutível |
| Servidor | Uvicorn local em `127.0.0.1` | Local; sem proxy, sem HTTPS, sem domínio |

### Loop do agente (orquestração)
Uma única mensagem do usuário pode exigir várias tools antes da resposta, então o agente
roda num **loop**: chama o modelo → se ele pedir tools, o backend executa, anexa os
resultados como `tool_result` e chama o modelo de novo → repete até o modelo devolver um
turno só de texto. As definições do loop ficam explícitas (não implícitas):

- **Loop limitado.** `MAX_ITERS` ≈ 6. A cada iteração, inspeciona o `stop_reason`:
  `tool_use` → executa e anexa resultados, continua; `end_turn` → devolve a resposta, sai;
  `max_tokens` → continua com um empurrão ou devolve parcial sinalizado. Estourou o teto →
  degrada com elegância ("não consegui concluir; aqui está o que reuni") e loga como
  anomalia. **O teto torna o pico de custo estruturalmente impossível.**
- **Contrato das tools: nunca jogam exceção pra dentro do loop.** Sucesso devolve
  `{dados…, source, as_of, is_cached}`; falha devolve `{error: <motivo>}`. O modelo traduz
  `error` em "não tenho esse dado". **Consequência importante: o guardrail antialucinação
  (guardrail 1) é aplicado *aqui*, no loop, não no prompt** — ele só dispara se o modelo
  receber um sinal de falha estruturado. Tool que estoura e derruba o loop, ou que é
  silenciosamente ignorada, fura o guardrail.
- **Paralelo vs. sequencial.** Tools independentes pedidas no mesmo turno rodam concorrentes
  (`asyncio.gather` + `httpx` async). As dependentes (ex.: `ler_carteira` antes de
  precificar cada papel) o modelo sequencia sozinho entre iterações — basta não pré-buscar.
- **Histórico e tokens.** Mantém o histórico da sessão até um teto de tokens; se crescer,
  descarta/resume os turnos mais antigos (no volume deste projeto, "últimos N turnos +
  system prompt" basta e dificilmente encosta no limite). Loga tokens **por iteração**, não
  só por conversa.
- **Confirmação como fronteira de turno, não pausa no loop.** O import é dois turnos:
  (1) colagem do texto do PDF → `importar_extrato(texto)` devolve o preview parseado como
  `tool_result` → o modelo apresenta "entendi isto: … confirma?" e o loop encerra (só
  texto); (2) o usuário confirma → o modelo chama uma tool **separada de escrita**
  (`gravar_posicoes`) → grava. Assim o guardrail "nunca grava sem confirmação" (guardrail 4)
  é garantido pela arquitetura: a escrita só existe no turno de confirmação.

---

## 4. Execução local

### 4.1 Como roda
- Roda no PC do usuário. `uvicorn` sobe o FastAPI ligado **só** a `127.0.0.1:8000`; o
  usuário abre `http://127.0.0.1:8000` no navegador. Um script de uma linha (ou um atalho)
  inicia o serviço quando ele quiser usar — uso sob demanda, não precisa ficar no ar.
- Como o serviço escuta apenas em `127.0.0.1`, **ele não fica exposto na rede**. Só quem
  está no próprio PC alcança. Isso elimina de uma vez HTTPS, domínio, reverse proxy,
  firewall de borda e sistema de login — nada disso é necessário no escopo local.

### 4.2 Segredos
- `.env` com a chave Anthropic (e o token da brapi) **nunca** no git. `.gitignore` desde o
  commit 1. Arquivo com permissão `600`. Mesmo local, segredo não vai para o repositório.

### 4.3 Backup
- O banco é um único arquivo SQLite. Backup simples: cópia periódica via
  `sqlite3 carteira.db ".backup '/backups/carteira-$(date +%F).db'"` (o `.backup` é seguro
  com o banco em uso; copiar o arquivo cru não é). Reter ~30 dias.
- **Cópia externa:** apontar a pasta de backup para uma pasta de nuvem que o usuário já
  use (Google Drive/Dropbox/iCloud) resolve o off-site sem custo novo. Backup só no mesmo
  PC não protege contra perder o PC.
- Testar a restauração uma vez. Backup não testado não é backup.

---

## 5. Modelo — Claude Sonnet 4.6

- **Preços (por milhão de tokens):** Sonnet 4.6 ≈ US$ 3 entrada / US$ 15 saída
  (confirmar o valor vigente na hora da build — preços e linha de modelos mudam).
  Pay-as-you-go: paga só pelo que usa.
- **Sem prompt caching (decisão deliberada).** O ganho do caching aparece *dentro* de uma
  sessão multi-turno (o system prompt grande seria relido do cache barato a cada turno);
  entre sessões o cache expira e não há ganho. Mas no volume deste projeto (~US$ 0,06 por
  conversa, poucas conversas/mês) a **economia absoluta é desprezível e não compensa a
  complexidade** de gerenciar breakpoints e manter o prefixo estável byte-a-byte. A
  arquitetura é cache-ready (o contexto dinâmico é injetado no fim → a parte fixa é um
  prefixo estável), então ligar no futuro — se for por **latência**, não por custo — é
  trivial. Por ora: **desligado**.
- **Ordem de grandeza observada:** pergunta simples (~8k in / 1k out) ≈ US$ 0,04; consulta
  de desvio (~30k in / 1k out) ≈ US$ 0,11; import de extrato completo (~19k in / 5k out)
  ≈ US$ 0,13. No uso sob demanda → poucos reais por mês, centavos em meses fracos. O custo
  alto no import se deve ao payload do texto do PDF — acontece uma vez por mês.
- **Controle de gasto:** logar tokens (input/output) por conversa **e por iteração do loop**
  para ter visibilidade. Volume é tão baixo que não há risco real de fatura surpreender.

---

## 6. Dados de mercado — brapi primária (produção), yfinance validação, Tesouro p/ RF pública

### 6.1 Cotações de papéis (renda variável)
A fonte **primária de produção é a brapi** (paga, oficial, agrega B3/CVM/BCB). O **yfinance**
entra **apenas para validação/bootstrap**: durante a Fase 0–1 ele prova a pipeline ponta a
ponta de graça (uma cotação real aparecendo no log) sem exigir conta paga, e depois
permanece só como **fallback** se a brapi falhar. **A troca para a brapi como primária é
prevista e faz parte do plano — não é "se um dia incomodar".** O motivo é concreto: o
yfinance é não-oficial (raspa o Yahoo) e, para tickers da B3 (`.SA`), atrasa, some, trata
proventos/desdobramentos de forma estranha e pode quebrar por dias quando o Yahoo muda
endpoint. Bom o bastante para *validar*, frágil demais para ser a fonte de produção de um
consultor que cita números. Como o acesso está encapsulado num `PriceProvider`, colocar a
brapi como primária é troca de configuração, não reescrita.

### 6.2 brapi — primária de produção (planejada)
- A brapi (paga, oficial, agrega B3/CVM/BCB, com SLA e reembolso de 7 dias) é a **fonte de
  produção planejada**. Plano **Startup — R$ 49,99/mês** cobre o caso (confirmar plano e
  preço vigentes na contratação, já que agora entra no custo-base — ver seção 14).
- **Sequência prevista:** validar a pipeline com yfinance (R$ 0) na Fase 0–1 → contratar a
  brapi → `BrapiProvider` vira **primário** e o yfinance recua para **fallback**. É troca de
  config no `CompositeProvider`, não reescrita.
- Rodar em "modo yfinance" (R$ 0) é um estado **transitório de validação**, não o destino.

### 6.3 Padrão `PriceProvider`
Interface única; o agente nunca chama a fonte de dados direto.

```
class PriceProvider(Protocol):
    def quote(self, ticker: str) -> Quote | None: ...

# Implementações:
#   BrapiProvider      (PRIMÁRIO de produção)
#   YFinanceProvider   (VALIDAÇÃO/bootstrap + FALLBACK)
#   TesouroProvider    (renda fixa pública — preço diário oficial; ver 6.7)
#
# CompositeProvider tenta na ordem configurada (RV: brapi -> yfinance; TD: tesouro);
# primeiro com dado válido vence.
# Todos falharam -> retorna None -> agente diz "não tenho esse dado" (guardrail 1).
```

`Quote` carrega sempre: `price`, `source` ("brapi"/"yfinance"/"tesouro"/"extrato"), `as_of`
(timestamp), `is_cached`. A `source` aparece para o usuário — transparência. Normalização
de ticker fica encapsulada em cada provider (brapi usa `PETR4` cru; yfinance usa
`PETR4.SA`).

### 6.4 Cache de cotações
- Tabela `quote_cache` no SQLite: ticker, price, source, fetched_at, payload.
- TTL padrão **15 min** (configurável). Serve velocidade **e** resiliência (fonte caiu →
  serve cache marcado `stale` com aviso). Para investidor de longo prazo, dado com alguns
  minutos é mais que suficiente.

### 6.5 Macro e notícias
- `contexto_macro()` → **API pública do BCB (SGS)**: Meta Selic, IPCA, câmbio. Oficial,
  gratuita, sem chave. Séries usadas (confirmadas em produção):
  - **432** — Meta Selic (% a.a., alvo Copom) — ex.: "14,75"
  - **433** — IPCA variação mensal (% a.m.) — ex.: "0,43"
  - **1** — Taxa de câmbio USD/BRL (compra, fim de período)
  - Nota: série 11 (taxa Selic *diária*, ex.: "0,054") foi descartada em favor da 432 que
    devolve diretamente o valor anualizado intuitivo.
  - CDI não incluído explicitamente (≈ Selic − 0,10 p.p.; o agente referencia pela Selic).
- `noticias()` → feeds **RSS** (InfoMoney/Valor) como fonte. (A brapi, já planejada como
  primária de cotações, pode complementar notícias para tickers cobertos.) Implementação na
  Fase 3.

### 6.6 REST vs. MCP da brapi
A brapi entra pela **API REST dela dentro das nossas próprias tools**, não pelo servidor
MCP. Motivo: manter controle total de `source`, `as_of`, cache e do guardrail
antialucinação — o MCP entregaria dados ao modelo por fora dessa disciplina.

### 6.7 Renda fixa pública: Tesouro Direto com preço diário oficial
O Tesouro Direto **tem preço diário oficial público** — o Tesouro Nacional publica os
preços/taxas dos títulos como **dado aberto** (Tesouro Transparente / B3; confirmar
endpoint e formato na build, como nas séries do BCB). Portanto o Tesouro **não** precisa
ficar preso ao valor datado do extrato nem depender de plano pago.
- Entra como um `TesouroProvider` próprio (mesmo contrato dos outros providers): devolve
  `price`, `source = "tesouro"`, `as_of` = data do pregão, `is_cached`.
- É um **preço diário (fim de dia)**, não um tick ao vivo — perfeito para quem rebalanceia
  1x/mês e muito melhor que um extrato de semanas atrás.
- **Por que importa:** Tesouro IPCA+/prefixado de longa duração tem marcação a mercado
  volátil. Era o membro mais volátil do conjunto "sem cotação"; trazê-lo para preço diário
  remove a maior fonte de erro do desvio (ver 8.1). CDB/LCI/LCA/fundos sem cotação pública
  seguem pelo extrato, com ressalva de data.

---

## 7. Carteira — atualização e modelo de dados

### 7.1 Atualização
BTG não tem API pública PF. Atualização **manual, cadência mensal**, com dois caminhos:
- **Edição manual** das posições (`POST /posicoes`, built-in desde a Fase 1) — confiável e
  simples; para ~15-30 posições leva poucos minutos por mês. Único caminho para RF privada
  (CDB/LCI/LCA), que não aparece no texto do PDF.
- **Import por colagem de texto** (Fase 2, operacional): BTG emite apenas PDF — **não há
  XLSX**. O usuário abre o extrato no leitor de PDF, faz Ctrl+A (selecionar tudo) → Ctrl+C
  (copiar) → cola na textarea "Importar extrato BTG" na UI. O parser extrai posições de RV
  (ações, FIIs, ETFs) e Tesouro Direto, mostra o **preview para confirmação** antes de
  gravar. Validado com extrato real 05/2026: 14/14 posições, total exato.
- Cotações de ativos com ticker são sempre via `PriceProvider`, nunca digitadas.

### 7.2 Renda variável vs. renda fixa — decisão tomada
O modelo de `Posicao` é genérico o bastante para abrigar qualquer classe, mas o **modo de
precificação difere por tipo**, e isso é explícito:
- **Com ticker (ações, FIIs, ETFs, BDRs):** preço ao vivo via `PriceProvider` (brapi
  primária → yfinance fallback). `source = "brapi"/"yfinance"`, `as_of` do momento da busca.
- **Tesouro Direto:** tem **preço diário oficial público** (via `TesouroProvider`, ver
  6.7). `source = "tesouro"`, `as_of` = data do pregão. Preço diário (fim de dia), não tick
  ao vivo — adequado à cadência mensal.
- **CDB, LCI/LCA, fundos (sem cotação pública):** **não há cotação ao vivo nem dado aberto.**
  O valor vem do **extrato do BTG**, gravado com `source = "extrato"` e `as_of` = data do
  extrato. O agente trata como dado datado, não preço atual — e avisa quando envelhece.

### 7.3 Modelo de dados (essencial)
- `Posicao`: id, ticker (nullable), nome, classe (enum: ACAO, FII, ETF, BDR, RF, TESOURO,
  FUNDO, CAIXA), quantidade, preco_medio, valor_mercado, source (brapi/yfinance/tesouro/
  extrato), as_of.
- `AlvoClasse`: classe → percentual-alvo. (Soma = 100%.)
- `AlvoAtivo`: ticker/identificador → percentual-alvo. (Ver 8.)
- `ConfigRebalanceamento`: banda absoluta (p.p.), banda relativa (%), piso de irrelevância
  (R$ e %), cadência. **Semeado com os padrões da seção 8; editável.**
- `PerfilRisco`: campos livres + texto que alimenta o system prompt.
- `QuoteCache`: ver 6.4.
- `SnapshotMensal`: data, JSON da carteira + valor total — histórico para análise.

### 7.4 Como exportar o extrato do BTG (colagem de texto)
O BTG **não oferece exportação em XLSX ou CSV** — apenas PDF. O fluxo para importar:
1. **BTG web/app:** Investimentos → Extratos → "Extrato da Conta Investimento" → período desejado → abrir/baixar PDF.
2. **No leitor de PDF** (Adobe, navegador, etc.): **Ctrl+A** (selecionar tudo) → **Ctrl+C** (copiar).
3. **Na UI do consultor:** botão "Importar extrato BTG" → colar (Ctrl+V) na textarea → "Importar".
4. O agente apresenta o preview → usuário confirma → `gravar_posicoes` salva.

**O que é extraído:** ações, FIIs, ETFs, Tesouro Direto (LFT/LTN/NTNB-P).
**O que NÃO é extraído:** RF privada (CDB/LCI/LCA) — não aparece como tabela estruturada no texto do PDF. Lance manualmente via `POST /posicoes`.
**Parser state-machine** em `app/tools/btg_parser.py` (Tesouro: LFT→"Tesouro Selic YYYY", LTN→"Tesouro Prefixado YYYY", NTNB-P→"Tesouro IPCA+ YYYY").

---

## 8. Alocação-alvo e bandas de rebalanceamento

### 8.1 Desvio em dois níveis (decisão do usuário)
O desvio é calculado e exibido em **dois níveis simultâneos**:
- **Por classe:** ex. alvo 60% ações / 25% FII / 15% RF; mostra o desvio de cada classe.
- **Por ativo individual:** ex. alvo 8% em PETR4; mostra o desvio de cada ativo.

Regras:
- Cada conjunto de alvos soma 100% no seu nível; o app valida ao salvar.
- Os alvos por ativo devem ser consistentes com os por classe; o app **avisa** se houver
  inconsistência, mas não impede — você decide.
- O dashboard mostra alvo, atual e desvio (em p.p. e em R$) nos dois níveis.

**Base de cálculo coerente (decisão).** O desvio é uma fração (posição ÷ total da carteira),
então misturar preço ao vivo com valor datado contamina o número. A regra adotada:
- **Snapshot coerente, "hoje, melhor esforço":** o `calcular_desvio` precifica tudo numa
  única base de data — ações ao vivo (brapi → yfinance), **Tesouro pelo preço diário
  oficial** (`TesouroProvider`, 6.7) e só CDB/LCI/LCA/fundos sem cotação pública carregados
  do extrato. O flag de banda (8.2) dispara sobre esse snapshot, **não** sobre uma visão ao
  vivo misturada. É a base correta para quem rebalanceia periodicamente: a decisão é contra
  a carteira num momento, não contra um tick intradiário. (O membro datado e volátil — o
  Tesouro — já saiu da equação por 6.7; o que resta carregado do extrato é lento e move
  pouco entre atualizações.)
- **Divulgação de frescor:** junto do desvio, a tool devolve a **fração do valor precificada
  ao vivo vs. carregada do extrato** e o **`as_of` mais antigo** — para o agente ressalvar
  quando a parte datada pesar.
- **Frescor das *posições*, não só dos preços:** a tool também expõe a **data da última
  atualização de posições** (edição manual ou import). Um aporte/resgate não lançado é um
  erro de *quantidade* — maior que qualquer erro de preço, e que nenhuma cotação ao vivo
  conserta. O agente sinaliza quando as posições estão envelhecendo.

### 8.2 Bandas de rebalanceamento (padrões propostos, ajustáveis)
Padrões semeados no `ConfigRebalanceamento`, alteráveis quando o usuário quiser:

- **Regra 5/25 (Swedroe), nos dois níveis:** rebalancear quando algo desviar do alvo em
  **5 pontos percentuais absolutos OU 25% relativos ao alvo, o que ocorrer primeiro.**
  - Classe grande (alvo 60%): a banda absoluta domina → age a 55%/65%.
  - Alvo pequeno (8%): a relativa domina → 25% de 8 = 2 p.p. → age a 6%/10%.
- **Cadência mensal:** avaliar 1x/mês; só sugerir rebalanceamento quando a banda romper.
  Dentro da banda → não fazer nada.
- **Piso de irrelevância:** não sugerir movimentar valores pequenos demais para compensar
  custo/imposto. Padrão: o maior entre **~R$ 500 ou ~0,5% do valor da carteira**.

`calcular_desvio()` aplica essas bandas **sobre o snapshot coerente (8.1)** e retorna, por
classe e por ativo, o desvio (p.p. e R$) **mais um flag "dentro/fora da banda"**, além da
**fração ao-vivo/extrato**, do **`as_of` mais antigo** e da **data da última atualização de
posições**. Quem decide se está fora da banda é a tool — o modelo apenas interpreta o
resultado (coerente com o guardrail antialucinação).

---

## 9. Ferramentas do agente

| Tool | Função | Fonte |
|---|---|---|
| `ler_carteira()` | posições atuais (com source/as_of) | SQLite |
| `importar_extrato(texto)` | lê texto colado do PDF BTG, extrai, retorna **preview para confirmação** (não grava) | colagem |
| `gravar_posicoes(...)` | grava as posições **após confirmação explícita** (turno separado — ver §3 / guardrail 4) | SQLite |
| `dados_ativo(ticker)` | preço, P/L, setor, variação | brapi → yfinance (fallback); `tesouro` p/ TD (+source) |
| `noticias(ticker_ou_tema)` | manchetes recentes | RSS (+brapi p/ tickers cobertos) |
| `calcular_desvio()` | atual vs alvo (classe e ativo) + flag de banda + fração ao-vivo/extrato + as_of mais antigo + data das posições | SQLite |
| `contexto_macro()` | juros, inflação, câmbio | BCB/SGS |

Princípio: poucas tools, cada uma com schema Pydantic explícito, cada número com `source`
e `as_of`.

---

## 10. Guardrails (inegociáveis)

1. **Nunca citar número que não veio de tool.** Sem dado → "não tenho esse dado". Proibido
   estimar de memória. E **separar fato (tool) de análise (raciocínio falível)** — nunca
   apresentar opinião como dado. *(Aplicado no loop do agente via tool-results estruturados
   — ver §3.)*
2. **Bloquear linguagem de execução.** Sempre consultivo ("considere", "sugiro avaliar").
   Nunca "comprei", "vendi", "executei".
3. **Disclaimer educacional** ao final de recomendações substantivas (não em toda mensagem
   trivial).
4. **Confirmação humana** dos dados extraídos antes de gravar no banco. *(Garantida pela
   arquitetura: a gravação é uma tool separada (`gravar_posicoes`) num turno posterior —
   ver §3.)*
5. **Marcar dado defasado.** Cotação de cache vencido — ou valor de renda fixa vindo do
   extrato — vem com aviso explícito de `as_of`.
6. **Antiviés de autoridade.** Quando o usuário demonstrar excesso de confiança, o agente
   lembra que é ferramenta de apoio com dados limitados — neutraliza o "o agente disse,
   então é verdade".

Detalhamento completo no arquivo `system_prompt_consultor_otimizado.md`.

---

## 11. Requisitos não-funcionais

- **Segurança:** chave Anthropic (e token da brapi) em `.env` (perm 600), nunca no código;
  `.gitignore` desde o commit 1. Serviço ligado só a `127.0.0.1` (não exposto na rede) →
  sem necessidade de auth, HTTPS ou firewall de borda no escopo local.
- **Cache de cotações:** SQLite com timestamp, reuso ~15 min, configurável (6.4).
- **Backup:** cópia local diária + cópia em pasta de nuvem + restauração testada (4.3).
- **Custo:** uso pessoal de baixo volume; logar tokens por conversa e por iteração do loop.
  Sem prompt caching (decisão — §5).
- **Observabilidade e saúde:** log estruturado de cada tool call (qual, source,
  sucesso/falha, latência). **Health-check:** endpoint que testa brapi, yfinance, BCB,
  Tesouro e o banco; o app exibe um aviso quando uma fonte está falhando há algum tempo —
  alarme contra "quebrar em silêncio". O yfinance (não-oficial) segue o mais propenso a
  quebrar, mas como recuou para fallback, isso deixou de ser crítico.
- **Erro de rede:** timeouts e 1 retry nas chamadas (httpx); falha → fallback (se houver) →
  cache stale → "não tenho esse dado".

---

## 12. Perfil de uso (orienta o design)

Investidor de longo prazo, rebalanceia 1x/mês conforme as bandas (8.2). Logo: **alertas
diários = ruído** e risco de overtrading. Uso **sob demanda**; resumo periódico (mensal,
alinhado ao rebalanceamento) a avaliar depois. **Não construir agendador de alertas
diários nesta etapa.**

---

## 13. Fases de construção

### Fase 0 — Fundações (local) ✅ CONCLUÍDA
- Estrutura de pastas, repo, `.gitignore` com `.env`, `uv` com lockfile.
- Esqueleto do FastAPI rodando em `127.0.0.1:8000` ("hello world" no navegador).
- SQLite + modelos (seção 7.3) incluindo stubs da Fase 5 (sem migração futura).
- Validar 1 chamada real de cotação (`PETR4.SA` via yfinance) e 1 de macro (Selic via BCB) — cada uma no log.
- **Saída alcançada:** localhost respondendo "ok", PETR4 R$ 41,25 (yfinance) e Selic 0,054% (BCB série 11) no log.

### Fase 1 — Núcleo consultivo ✅ CONCLUÍDA
- `PriceProvider`: `BrapiProvider` (stub pronto) + `YFinanceProvider` (ativo) + `TesouroProvider` + `CompositeProvider` + cache 15 min.
- **Loop do agente** com MAX_ITERS=6, tool dispatch paralelo (`asyncio.gather`), logging de tokens por iteração e por conversa.
- Tools `ler_carteira`, `dados_ativo` e `contexto_macro` (BCB séries 432/433/1).
- Edição manual de posições via `GET/POST/DELETE /posicoes` (incl. RF via valor do extrato).
- System prompt ligado (`system_prompt_consultor_otimizado.md`), guardrails 1–6 ativos.
- `ConfigRebalanceamento` semeado com padrões §8.2; `PerfilRisco` e `AlvoClasse` semeados.
- Health-check em `/health` (testa yfinance, BCB e SQLite).
- **Saída alcançada:** "como está minha carteira hoje?" respondido em 3 iterações, ~US$ 0,045/conversa.

### Fase 1.5 — Spike do parser de colagem de texto ✅ CONCLUÍDO
- **Decisão:** BTG não emite XLSX — apenas PDF. Adotada a **opção B (colagem de texto)**:
  usuário copia o texto do PDF (Ctrl+A / Ctrl+C no leitor) e cola numa textarea da UI.
- Spike implementado em `scripts/spike_btg_parser.py` e validado contra extrato real (05/2026).
- **Resultado:** 14/14 posições extraídas corretamente (5 Tesouro, 5 ações, 1 ETF, 3 FIIs);
  total R$ 44.363,04 bate exatamente com o extrato.
- **Limitação confirmada:** RF privada (CDB/LCI/LCA) não aparece como tabela estruturada no
  texto do PDF — segue via edição manual (`POST /posicoes`). Não é bloqueio.
- Parser state-machine: seções detectadas por markers; Detalhamento/Movimentação ignorados;
  LFT→"Tesouro Selic YYYY", LTN→"Tesouro Prefixado YYYY", NTNB-P→"Tesouro IPCA+ YYYY".

### Fase 2 — Import + análise de carteira ✅ CONCLUÍDA (gap menor pendente)
- `importar_extrato(texto)`: parser BTG integrado em `app/tools/btg_parser.py`, preview formatado por classe — nunca salva (guardrail 4 por arquitetura).
- `gravar_posicoes(posicoes)`: upsert por ticker/nome, source="extrato", only no turno de confirmação.
- `calcular_desvio()`: snapshot coerente (RV+Tesouro ao vivo via asyncio.gather, RF pelo extrato), desvio em p.p. e R$, flag de banda 5/25, fração ao-vivo/extrato, as_of mais antigo, data última atualização de posições.
- UI: modal de colagem (botão "Importar extrato BTG" no header).
- **Gap:** `SnapshotMensal` — modelo de dados existe, mas a tool/endpoint de tirar o snapshot mensal não foi implementada. Mover para Fase 3 (é conveniência, não bloqueio).
- **Saída alcançada:** import → preview → "sim" → 14 posições gravadas → "minha carteira saiu do alvo?" com análise completa, ~US$ 0,11/consulta de desvio.

### Fase 3 — Notícias + UI polida + SnapshotMensal ← PRÓXIMA
- `noticias(ticker_ou_tema)`: feeds RSS (InfoMoney/Valor Econômico). Implementar parser de feed + cache de manchetes por ticker.
- `SnapshotMensal`: endpoint/tool para tirar fotografia mensal da carteira (modelo já existe — apenas a lógica de gravação falta).
- Polir a UI web local: dashboard de carteira (tabela posições + desvio visual), melhorias no chat. Sem PWA/offline/manifest — não necessários no escopo local.
- **Saída:** app local usável com notícias por ticker e dashboard de carteira; snapshot mensal disponível.

### Fase 4 — (Depois) Recomendação de rebalanceamento
- Camada de sugestão mensal, **só** quando o parsing estiver validado e os dados
  confiáveis. Resumo mensal opcional alinhado ao rebalanceamento.
- **Saída:** sugestões de rebalanceamento consultivas, fundamentadas, respeitando as
  bandas.

### Fase 5 — (Depois) Estratégia persistente + modo proposta
- **Persistência de estratégia** (tese + planos futuros + tool `atualizar_estrategia` com
  confirmação e filtro comportamental): guardar a estratégia narrativa e os planos de
  compra/venda futuros, mutáveis só por ato **deliberado e confirmado** (espelha
  `gravar_posicoes`). **Pós-Fase 2.** Stubs de schema
  (`EstrategiaInvestimento`/`PlanoFuturo`/`HistoricoEstrategia`) podem entrar já na Fase 0
  para evitar migração. Spec detalhada em `spec_persistencia_estrategia.md`.
- **Modo proposta (what-if de pré-trade):** estende o `calcular_desvio` para uma carteira
  hipotética e checa as travas (liquidez ≥ 60% > D+6, dividendos) **antes** de uma mudança
  real. Decisão-apoio, **nunca execução**. Só após desvio + import validados. **Backtest e
  projeção de retorno ficam fora** (viés de recência/market-timing; dependeriam do yfinance
  histórico, a fonte mais fraca).
- **Saída:** estratégia e planos versionados e injetados em toda sessão; what-if respondendo
  "se eu fizer X, como fica o desvio e as travas?".

### Transição planejada — yfinance (validação) → brapi (produção)
- Não é opcional: faz parte do plano. Validar a pipeline em modo yfinance (R$ 0) →
  contratar a Startup → `BrapiProvider` vira primário, yfinance recua para fallback. Troca
  de config no `CompositeProvider`, sem reescrever. O único motivo para adiar é encurtar a
  fase de validação; o destino é a brapi.

---

## 14. Custos consolidados

| Frente | Escolha | Custo/mês (aprox.) |
|---|---|---|
| Execução | Local (PC do usuário) | R$ 0 |
| Backup off-site | Pasta de nuvem já existente | R$ 0 |
| Cotações RV (validação) | yfinance | R$ 0 |
| Cotações RV (produção) | **brapi Startup (planejada)** | **~R$ 49,99** |
| Tesouro (RF pública) | Dado aberto do Tesouro | R$ 0 |
| Macro / Notícias | BCB (SGS) / RSS | R$ 0 |
| API modelo | Sonnet 4.6, uso sob demanda | ~R$ 5–30 |
| **Total (validação, modo yfinance)** | | **~R$ 5–30/mês** |
| **Total (produção, com brapi)** | | **~R$ 55–80/mês** |

Na fase de validação (modo yfinance) o custo é só a API do modelo — poucos reais, centavos
em meses fracos. Em produção, a brapi é o item planejado que entra no custo-base (~R$ 50);
a abstração `PriceProvider` já está pronta para ela e o Tesouro fica de graça via dado
aberto.

---

## 15. Riscos remanescentes e mitigação

| Risco | Mitigação no plano |
|---|---|
| yfinance instável (fonte não-oficial, usada só p/ validação/fallback) | brapi é a primária planejada de produção; yfinance recua a fallback; + cache stale + "não tenho dado" + health-check |
| Loop do agente não terminar / custo disparar | teto de iterações `MAX_ITERS` (§3); tools nunca estouram (tool-results estruturados de erro) |
| Desvio contaminado por dado datado | snapshot coerente + Tesouro ao vivo (6.7) + divulgação de fração ao-vivo/extrato e as_of mais antigo (8.1) |
| Parser de extrato (colagem PDF) | Spike validado com extrato real 05/2026: 14/14 posições corretas. Limitação conhecida: RF privada não estruturada no PDF → edição manual. Se o BTG mudar o layout do PDF, o parser pode quebrar — monitorar e corrigir os markers. |
| Perder o arquivo SQLite | Backup local + cópia em nuvem + restauração testada |
| Bit rot (libs/formato mudam) | Logs + health-check + lockfile `uv`. Ter a brapi (oficial) como primária reduz o bit rot de fonte não-oficial; yfinance fica de fallback |
| Renda fixa sem cotação pública (CDB/LCI/LCA/fundos) | Valor do extrato com source/as_of + aviso de dado datado. Tesouro **não** entra aqui: tem preço diário oficial (6.7) |
| Excesso de confiança no agente | Guardrail 6 (antiviés) + disclaimer + separação fato/análise |
| Escopo emocional (virar day-trade) | Sem agendador diário; uso sob demanda; bandas mensais |
| Dado de mercado divergir do BTG | `source`/`as_of` visível; confirmação no import |

---

## 16. Pontos deixados explicitamente para depois (fora do escopo atual)

Registrados para não serem confundidos com esquecimento:
- Servidor MCP da brapi (decisão: usar REST nas próprias tools — 6.6).
- Agendador de resumo mensal automático (avaliar após Fase 3).
- Camada de recomendação de rebalanceamento (Fase 4).
- Acesso fora do PC / pelo celular (exigiria expor na rede + auth/HTTPS — fora de escopo).
- Ajuste fino das bandas de rebalanceamento (padrões propostos na 8.2, mudáveis quando
  quiser).
- Marcação a mercado de CDB/LCI/LCA e fundos sem cotação pública (seguem pelo extrato
  datado; não há dado aberto equivalente ao do Tesouro).
- **Carteiras simuladas — modo proposta (what-if de pré-trade):** estende o
  `calcular_desvio` a uma carteira hipotética e checa as travas antes de uma mudança real
  (Fase 5, §13). Decisão-apoio, não execução. **Backtest e projeção de retorno ficam
  explicitamente fora.**
- **Persistência de estratégia (tese + planos futuros + `atualizar_estrategia`):** estratégia
  narrativa e planos de compra/venda futuros, mutáveis só por confirmação explícita e
  deliberada, com filtro comportamental em medo/euforia (Fase 5, §13). Spec em
  `spec_persistencia_estrategia.md`.

> Promovidos para dentro do escopo nesta revisão: **brapi como primária de produção** (era
> "assinar se incomodar" — agora planejada, 6.2) e **preço diário do Tesouro** (era
> "exigiria brapi Pro" — agora via dado aberto, 6.7).

---

## 17. Próximo passo

**Fase 3:** `noticias(ticker_ou_tema)` via RSS + `SnapshotMensal` + UI polida (dashboard de carteira). Confirmar ao fim antes de avançar para a Fase 4.

> **Disclaimer:** este projeto produz conteúdo educacional/informativo. Não é
> recomendação de investimento. Você é o único responsável pelas decisões.
