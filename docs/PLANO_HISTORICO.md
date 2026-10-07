# Plano — Histórico de extratos e desempenho da carteira

> ## EXECUTADO — no ar desde 2026-10-06 (release v2 no Fly)
>
> Escopo fechado com o dono em 05/10/2026 e plano aprovado. Os Blocos 0 a 11 estão no código,
> com 190 testes verdes (também em Python 3.12, o da imagem) e QA no navegador. Falta só a
> rotina do dono em produção (seção "Deploy e rotina pós-deploy"). Progresso:
>
> - [x] Bloco 0 — plano no repo, script de inspeção, dados pessoais fora dos arquivos versionados
> - [x] Bloco 1 — parser v2 (razão da conta, lotes de RF, movimentações, sanitização)
> - [x] Bloco 2 — classificador de lançamentos e regras do dono
> - [x] Bloco 3 — motor do total, proventos, data de corte, preview
> - [x] Bloco 4 — benchmarks (CDI e IPCA do BCB)
> - [x] Bloco 5 — APIs de extratos (lote, exclusão, lançamentos, regras); SnapshotMensal aposentado
> - [x] Bloco 6 — tool `desempenho_carteira` e system prompt
> - [x] Bloco 7 — UI: tela Histórico, aba Desempenho, painel Carteira
> - [x] Bloco 8 — UI: aba Extratos
> - [x] Bloco 9 — composição por classe e ativo, comparação, CSV
> - [x] Bloco 10 — UI de composição, comparação e exportação; tool com `nivel`
> - [x] Bloco 11 — documentação (README, PLANO_XLSX, PLANO_DEPLOY_FLY, este plano)
> - [x] Deploy — A e B num só, em 06/10/2026, autorizado pelo dono; backup antes
>   (`backups/carteira-fly-20261006-pre-historico.db`). Registro em PLANO_DEPLOY_FLY §10

---

## Contexto

O app mostrava só a carteira **atual**. O backend do histórico de extratos já existia (commit
`de2dc39`: cada import arquiva o mês em `ExtratoImportado` e grava um ponto em
`SnapshotMensal`; rotas `GET /extrato/historico` e `/extrato/historico/{data}`), mas **nenhuma
tela e nenhuma tool do agente** usavam isso. "Desempenho" era o sparkline do painel Carteira e o
"Δ desde o snapshot" — **variação de saldo**, que mistura aporte com rendimento.

O dono quer: (1) navegar pelos extratos arquivados; (2) ver a **rentabilidade real** da carteira
(descontando aportes e resgates) contra CDI e IPCA, por mês e acumulada, no total, por classe e
por ativo, com a renda passiva; (3) que o consultor responda perguntas de desempenho no chat.
Resultado: uma tela **Histórico** (abas Desempenho e Extratos), um motor de rentabilidade
alimentado só pelos extratos oficiais e a tool `desempenho_carteira`.

## Decisões do dono (05/10/2026 — não reabrir)

1. **Rentabilidade descontando aportes lidos do extrato.** O parser passa a ler o razão da aba
   Conta Corrente; TED/PIX/transferências viram APORTE/RESGATE; retorno mensal por Modified
   Dietz, encadeado (TWR). Lançamento não reconhecido → o dono classifica na tela. Meses já
   arquivados sem o razão precisam ser reenviados.
2. **Série = só fechamentos mensais do extrato.** O botão de snapshot manual (câmera) sai; os
   snapshots manuais antigos ficam no banco, fora de qualquer série.
3. **Tela própria "Histórico"** em largura total, abas **Desempenho** e **Extratos**, aberta pela
   sidebar; o painel Carteira mantém o sparkline e ganha um atalho.
4. **Retroativo:** o dono tem meses antigos em XLSX → upload de vários arquivos de uma vez.
5. **Benchmarks:** CDI e IPCA (retorno real). Ibovespa e IFIX fora.
6. **Detalhe:** carteira total + proventos por mês + por classe + por ativo.
7. **Lote confirmado na tela**, só para meses que não mexem na carteira; mês mais novo que a
   carteira continua exigindo o "sim" no chat (guardrail 4).
8. **Extras:** tool `desempenho_carteira`, comparar dois meses, excluir um mês, exportar CSV.

## Fatos verificados (05/10/2026)

- **Produção:** nenhum extrato arquivado ainda; as 15 posições ativas têm `chave_externa` e
  `as_of = 2026-08-10`. Os 3 `SnapshotMensal` existentes são manuais, de antes da reconciliação
  das posições — não se comparam com os totais do extrato.
- **Bug latente:** o modo somente-histórico de `gravar_posicoes` só consultava
  `ExtratoImportado`. Sem nenhum mês arquivado, importar pelo chat um mês anterior a 10/08
  reconciliaria a carteira para trás.
- **Razão da conta:** `_tabelas` já separa a tabela "Movimentações" da aba Conta Corrente, e ela
  fecha (saldo anterior + Σ movimentações = saldo final = CAIXA = Sumário). **Não há exemplo
  real** de débito, TED/PIX, compra/venda ou aplicação/resgate de Tesouro — ver
  "Vocabulário observado".
- **Tesouro:** os lotes do `Detalhamento` têm `Aquisição` e `Valor Compra R$`, mas
  `_acumula_lotes_rf` os descartava. Resgate não aparece na aba Renda Fixa — só no razão.
- **Sumário:** o Total Bruto inclui Valores em Trânsito — é o número certo para rentabilidade
  (competência: o provento a receber compensa a queda na data-ex no mesmo mês).
- **BCB:** CDI pela série 12 composta na janela [fim(M−1), fim(M)) dá jul/26 = **1,2152%** (a
  4391 arredonda para 1,22). Faixa sem dados → HTTP 404 com JSON "Value(s) not found" (ainda não
  publicado); HTML "Requisição inválida!" = erro; a série diária aceita no máximo 10 anos por
  consulta. O mês corrente vem parcial.
- **Referência para testes:** a rentabilidade de um mês sem fluxo externo é
  `(V_fim − V_ini) / V_ini` — na fixture sintética, a constante
  `RENTABILIDADE_PCT_FIXTURE` de `tests/gerador_extrato.py`.
- **Privacidade:** `ExtratoImportado.arquivo` gravava o nome do arquivo do BTG, que é o número da
  conta. Descrições de TED/PIX podem trazer nome, CPF, agência e conta de contraparte. O
  repositório é público: nenhum dado pessoal em arquivo versionado.
- **Frontend:** sem router; `Sparkline` usa x por índice e id de gradiente global;
  `noUnusedLocals` quebra o build com import sobrando; `ModalImport` reiniciava durante o
  streaming (callback novo a cada render) e upload que terminava com o chat ocupado se perdia.

## Decisões técnicas deste plano (vetáveis sem quebrar o resto)

1. **Data de corte gravada à parte** (corrige o bug latente): tabela `ReferenciaCarteira` (uma
   linha), atualizada só por `gravar_posicoes` no modo normal e semeada no boot com
   `max(Posicao.as_of)` das posições ativas com `chave_externa`.
   `data_de_corte = max(extrato_mais_recente, referência)`. Edição manual de posição não mexe no
   corte (o `as_of` de `POST /posicoes` e do `gravar_posicoes` manual vem de quem chama).
2. Patrimônio do mês = **Total Bruto do Sumário** (inclui trânsito); rentabilidade **bruta**
   (antes de IR), comparável ao CDI.
3. Total e classe: **Modified Dietz**. Ativo: **TWR por preço unitário**
   (`(P_fim + renda por unidade) / P_ref − 1`) + resultado em R$ — o Dietz por ativo explode com
   compra no fim do mês ou saída total.
4. CDI = série 12 composta; IPCA = 433; só meses completos; **nada de rede** no upload, no lote
   ou no preview.
5. Classificação de lançamentos **no cálculo** (retroativa); o payload guarda só seq, data,
   descrição sanitizada, valor com sinal e saldo. Linha não classificada conta como interna no
   número **provisório**.
6. Primeiro mês da conta (V_ini = 0) e períodos que não são mês civil ficam fora da série.
7. `SnapshotMensal` **para de ser gravado**; `POST /snapshots` e o botão de câmera saem;
   `GET /snapshots` fica como legado somente leitura. Séries vêm de `ExtratoImportado`.
8. Excluir o mês mais recente arquivado → 409.
9. Gráficos em SVG próprio (sem biblioteca nova).

## Arquitetura

### Parser v2 — `app/tools/btg_xlsx_parser.py`
- Campos novos em `ExtratoParsed` (todos com default; payload sem `versao_parser` = v1):
  `versao_parser = 2`, `saldo_inicial_conta`, `lancamentos_conta: [{seq, data, descricao, valor,
  saldo}]`, `lotes_rf: [{chave_externa, sigla, vencimento, aquisicao, quantidade, preco_compra,
  valor_compra, taxa_compra, preco_atual, saldo_bruto}]`. Como o upload grava `bruto =
  extrato.to_dict()`, tudo isso é arquivado sem mudar `ExtratoImportado`.
- `proventos`/`movimentacoes` ganham `classe` (do título do bloco), `operacao`
  (COMPRA | VENDA | PROVENTO | OUTRO), `preco`, `corretagem`, `amortizacao`.
- `checagem.conta_corrente`: saldo inicial + Σ = saldo final; créditos/débitos vs totais do
  extrato; vs CAIXA; vs Sumário anterior (tolerância R$ 0,05). `checagem.movimentacao_rv` vs
  "Total de Compras/Vendas/Proventos".
- "Saldo Anterior" vira `saldo_inicial_conta`; "Saldo Final + Rendimento Provisionado…" é
  lançamento. Sinal derivado da diferença de saldos (formato dos débitos ainda desconhecido);
  linha sem data herda a anterior.
- **Sanitização no parser** (única camada que vê o XLSX): linha de PIX/TED/DOC/TRANSF mantém só
  palavras de um vocabulário fixo (RECEBIDO, ENVIADA, ENTRE CONTAS, CUSTÓDIA…); as demais
  mascaram CPF/CNPJ, conta com dígito e sequências de 5+ dígitos, preservando tickers e datas.
  Nenhuma descrição em log. `mascarar_nome_arquivo` para `ExtratoImportado.arquivo`.
- Armadilhas: nos lotes, usar `_idx(tab, "aquisicao")` e `_idx(tab, "preco r$")` — `"data"`
  casa com "Data inicial de liquidez" e `"preco"` com "Preço Compra".

### Tabelas novas (só `create_all`, sem migração)
- `RegraLancamento`: `escopo` (texto | linha | ativo_mes), `modo` (exato | prefixo | contem),
  `padrao`, `sinal`, `data_referencia`, `seq`, `impressao` (hash da linha), `tipo`, timestamps.
- `IndicadorMensal`: `serie` (CDI | IPCA), `mes` ('YYYY-MM'), `valor_pct`, `fonte`, `obtido_em`;
  único por (serie, mes); só mês completo é gravado.
- `ReferenciaCarteira`: `data_referencia`, `origem` (import | semente), `atualizado_em`.
- Registradas em `app/models/__init__.py` e na lista de `create_tables()` (`app/database.py`).

### Módulos novos
| Módulo | Papel |
|---|---|
| `app/tools/lancamentos.py` | classificador puro: `TIPOS`, `REGRAS_PADRAO`, `classificar`, `classificar_mes`, `padrao_sugerido` |
| `app/tools/regras_lancamento.py` | CRUD das regras com Session; `carregar_regras_seguro()` (lista vazia sem tabela) |
| `app/tools/desempenho.py` | motor puro: Dietz, série, janelas, benchmarks, proventos; depois composição |
| `app/tools/desempenho_servico.py` | orquestração com Session, CSV, `tool_desempenho_carteira` |
| `app/tools/benchmarks.py` | SGS por intervalo + cache em `IndicadorMensal` (padrão de `macro._fetch_serie`: timeout 8 s, nunca levanta) |
| `app/tools/extrato_lote.py` | staging do lote em memória (um lote, TTL 1 h, lock), separado do slot do chat |
| `app/api/desempenho.py` | rotas `/desempenho*` |
| `app/api/extrato_lote.py` | `/extrato/lote*`, `/extrato/regras*`, `/extrato/comparar` |

Só rotas e `tool_*` importam `engine`; o resto recebe `Session` (menos módulos para os testes
trocarem).

### Endpoints
Todos protegidos pelo `AuthGuardMiddleware`. `/desempenho` entra no `API_ROUTES` de
`frontend/vite.config.ts`. Rotas `/extrato/historico/<sufixo>` são declaradas **antes** de
`/historico/{data_referencia}`.
- `GET /desempenho`:
  - `meses[]`: mes, data_ini, data_fim, status, patrimonio_ini/fim, patrimonio_posicoes_fim,
    aportes, resgates, ganho, rentabilidade_pct, cdi_pct, pct_do_cdi, ipca_pct,
    retorno_real_pct, proventos, nao_classificados, avisos;
  - `janelas` {mes, ano, 12m, inicio}: considerados, faltantes, parcial, provisorio,
    rentabilidade, ganho, aportes_liquidos, CDI, % do CDI, IPCA, real, ipca_pendente, anualizado;
  - `proventos` (por_mes, ultimos_12m com yield, por_ativo_12m), `pendencias`,
    `benchmarks` {status, cdi_ate, ipca_ate}.
- `GET /desempenho/composicao?janela=` (classes, caixa, trânsito, ativos, resíduo) ·
  `GET /desempenho/ativo?chave=&janela=` · `GET /desempenho/export.csv?tipo=mensal|ativos&janela=`
  (`;`, vírgula decimal, BOM UTF-8).
- `POST /extrato/lote` (até 24 XLSX de 5 MB) → itens com `status` ∈ novo | substitui |
  reenvio_do_atual | diverge_da_carteira | mais_novo_que_carteira | periodo_nao_mensal |
  duplicado_no_lote | erro, mais `selecionavel`, `selecionado_padrao` e resumo do mês ·
  `POST /extrato/lote/{id}/confirmar {datas}` · `DELETE /extrato/lote/{id}`.
- `GET /extrato/historico` enriquecido (mes, patrimonio, tem_lancamentos, nao_classificados,
  checagens, mais_recente) · `DELETE /extrato/historico/{data}` (204 | 409 se mais recente | 404)
  · `GET /extrato/historico/{data}/lancamentos` (tipo, origem da classificação, `padrao_sugerido`).
- `GET/POST /extrato/regras`, `DELETE /extrato/regras/{id}` (o POST diz quantos meses e
  lançamentos a regra afeta).
- `GET /extrato/comparar?de=&ate=`: entraram, saíram e mudaram por `chave_externa`; classes;
  aportes, proventos e rentabilidade entre as datas.
- `GET /dashboard`: `ultimo_snapshot` → `ultimo_fechamento` (de `ExtratoImportado`).

### Tool `desempenho_carteira`
Entradas opcionais: `periodo` (mes | ano | 12m | inicio; padrão 12m), `nivel`
(carteira | classe | ativo; padrão carteira), `mes` ('AAAA-MM'). Saída compacta (< 2,5 KB;
< 3 KB com `nivel=ativo`, top 10 por |resultado|): source, as_of, período (considerados e
faltantes), rentabilidade, ganho, aportes líquidos, patrimônio início/fim, CDI, % do CDI, IPCA,
real, proventos, `status` (ok | parcial | provisório) com `avisos`, série mensal em formato
colunar. Sem mês arquivado → `tool_error`.

## Algoritmos

**Rentabilidade do mês (total).** `V_ini = sumario.anterior.total.bruto`,
`V_fim = sumario.atual.total.bruto`, `D = (data_fim − data_ini).days`. Para cada fluxo externo F
(APORTE +, RESGATE −, valor com sinal do razão) na data t: `w = (data_fim − t).days / D`.
`ganho = V_fim − V_ini − ΣF`; `r = ganho / (V_ini + Σ w·F)`.
Exemplo de teste: 100.000 → PIX +2.000 em 16/07 → 103.000 ⇒ **0,9904%**.
- Status (vale o primeiro que se aplica): `periodo_parcial` → `sem_base` (V_ini ≤ 0) →
  `sem_lancamentos` (payload v1) → `provisorio` (há NAO_CLASSIFICADO ou o razão não fecha) →
  `ok`. Mês ausente entre o primeiro e o último arquivado = `lacuna`.
- Avisos: continuidade (|V_fim(M−1) − V_ini(M)| > R$ 1; vale o V_ini do próprio extrato) e
  `fluxo_relevante` (Σ|F| > 10% de V_ini).

**Janelas.** mes; ano (jan → último fechamento); 12m; inicio (primeiro mês ok/provisório).
- `R = Π(1+r) − 1` só sobre meses ok/provisório. `parcial` se faltar mês na janela;
  `provisorio` se algum mês considerado for. Anualizado só em `inicio` com ≥ 12 meses.
- Benchmarks sobre **os mesmos meses**: `CDI = Π(1+cdi) − 1`, `% do CDI = R/CDI`,
  `real = (1+R)/(1+IPCA) − 1`. IPCA não publicado → `null` + `ipca_pendente`.

**Classificação (no cálculo).**
- Precedência: regra de linha (com `impressao` igual) → regras de texto do dono (exato →
  prefixo mais longo → contém, respeitando o sinal) → `REGRAS_PADRAO` → `NAO_CLASSIFICADO`.
- Externos: APORTE, RESGATE. Internos: COMPRA_RV, VENDA_RV, APLICACAO_RF, RESGATE_RF, PROVENTO,
  ALUGUEL, RENDIMENTO_CAIXA, IMPOSTO, TAXA, OUTRO_INTERNO. Só a fronteira externo/interno muda o
  total.
- Padrões iniciais conservadores: proventos e "rendimento provisionado" pela fixture;
  PIX/TED/DOC/transferência pelo sinal; transferência de custódia e o resto ficam não
  classificados até o vocabulário real ser mapeado.

**Proventos.** Fonte = `proventos` do parser (líquido); funciona inclusive nos arquivos v1, sem
reenvio. Amortização fica separada (entra no retorno, não no yield). Cupom de Tesouro e aluguel
vêm do razão (v2). Yield 12m = renda 12m / patrimônio em posições; por ativo, também sobre o custo.

**Composição (classe e ativo).** Por `chave_externa`, entre os arquivos de M−1 e M:
- Fluxos: compras/vendas de RV pela movimentação (valor líquido, data); compras de Tesouro/RF
  pelos lotes com `aquisicao` no mês; resgates de RF pelo razão (RESGATE_RF casado pelo título;
  sem casamento → estimado `q_res × (P0+P1)/2`). Renda = proventos do ticker + cupons e aluguel
  casados no razão.
- Saídas: resultado R$ = `V1 − V0 − compras + vendas + renda`; % do ativo = TWR por preço;
  classe = Dietz sobre os agregados.
- Desdobramento/grupamento é detectado pelo fator de quantidade sem negociação. Outra mudança
  de quantidade sem negociação vira pendência que o dono resolve com regra `ativo_mes`: evento
  societário, ou aporte/resgate em ativos (este vira fluxo externo também no total).
- Identidade: `ganho_total = Σ classes + (rendimento de caixa + custos) + Δtrânsito + resíduo`;
  resíduo > max(R$ 5; 0,05% de V_ini) gera aviso.
- Exemplo de teste (BBAS3): 100 × 20,00 → compra de 50 em 10/07 por 1.050,30 → provento de
  10,00 em 20/07 → fecha a 22,00 ⇒ resultado **R$ 259,70**; TWR **10,50%**; Dietz **9,59%**.

**Lote, corte e exclusão.**
- `data_ref > corte` (ou corte nulo) → `mais_novo_que_carteira` (vai pelo chat; o primeiro
  extrato de uma base vazia também).
- `data_ref = corte` → `reenvio_do_atual` se as posições batem por `chave_externa` (quantidade
  ± 1e-6, valor ± R$ 1); senão `diverge_da_carteira`.
- `data_ref < corte` → `novo` ou `substitui` (desmarcado por padrão se o arquivado já tem razão
  ou se a checagem diverge).
- Confirmar revalida contra o corte atual e chama `arquivar_extrato`
  (`app/tools/extrato_arquivo.py`) para todos numa transação; **nunca toca em `Posicao`**.
- Excluir: 409 no mais recente; remove também as regras de linha/ativo_mes do mês e o
  `SnapshotMensal` de origem extrato daquela data.

## Blocos de trabalho (nesta ordem)

**Bloco 0 — Plano no repo, mapeamento do real, higiene de privacidade** ✅
- Este documento.
- `scripts/inspecionar_extrato.py` (somente leitura; reusa `_tabelas`, `_aba`, `_norm`, `_idx`):
  imprime só o período da Capa, títulos/cabeçalhos, prefixos agregados das descrições do razão
  (contagem e sinal), valores distintos de "Transação" em RV e lotes com aquisição no período.
  Nunca imprime nome, CPF ou conta.
- **Dono:** colocar em `uploads/` XLSX de meses com TED/PIX, compra/venda, aplicação/resgate e
  cupom de Tesouro. A seção "Vocabulário observado" registra só padrões genéricos; testes usam
  linhas sintéticas.
- Nome do titular e número da conta retirados de `docs/PLANO_XLSX.md` e de
  `scripts/test_fase2.py`.

**Bloco 1 — Parser v2**
- `app/tools/btg_xlsx_parser.py`: `_parse_lancamentos_conta`, `_checagem_conta`,
  `sanitizar_descricao`, `mascarar_nome_arquivo`, emissão de lotes a partir de
  `_acumula_lotes_rf`, `_parse_movimentacao` enriquecido, `_checagem_movimentacao_rv`;
  integração em `parse_btg_xlsx`.
- Testes: `tests/planilhas.py` (helpers que alteram a fixture sintética em memória e acrescentam
  lançamentos, movimentações e lotes, recalculando saldos, totais e Sumário), `tests/conftest.py`
  (`DATABASE_URL` temporário antes de qualquer import do app), `tests/test_parser_conta_corrente.py`.
- Pronto: a fixture dá 5 lançamentos, saldo inicial = `CAIXA_INI_FIXTURE` e conferência ok;
  8 lotes com chaves iguais às das posições; débito sintético sai com o sinal certo;
  PIX/TED/CPF/conta sanitizados com tickers e datas intactos; testes antigos verdes.

**Bloco 2 — Classificador e regras**
- `app/tools/lancamentos.py`, `app/tools/regras_lancamento.py`, `app/models/regra_lancamento.py`;
  `tests/test_lancamentos.py`.
- Pronto: a fixture dá 4 PROVENTO + 1 RENDIMENTO_CAIXA; precedência coberta por testes; regra
  criada depois do arquivamento muda a leitura seguinte.

**Bloco 3 — Motor do total, proventos, data de corte, preview**
- `app/tools/desempenho.py`, `app/tools/desempenho_servico.py`, `app/api/desempenho.py`;
  `app/models/referencia_carteira.py` + semente em `app/seeds.py`.
- `app/tools/extrato_arquivo.py`: `data_de_corte`; `arquivar_extrato` mascarando `arquivo`.
  `gravar_posicoes` passa a usar o corte e atualiza `ReferenciaCarteira` no modo normal.
- `app/tools/extrato.py`: `rentabilidade_do_mes` no preview (sem CDI, sem rede); a nota do
  comparativo aponta para ela. `frontend/vite.config.ts`: `/desempenho`.
- Pronto: 0,9904% (exemplo manual do plano) e `RENTABILIDADE_PCT_FIXTURE` (fixture sintética);
  status, lacunas e janelas cobertos. Cenário de produção (0 arquivos, posições em 2026-08-10):
  import de 2026-06-30 pelo chat → somente-histórico. Edição manual de posição não move o corte.

**Bloco 4 — Benchmarks**
- `app/tools/benchmarks.py`, `app/models/indicador_mensal.py`; testes com `httpx.MockTransport`.
- Pronto: CDI composto a partir de diárias simuladas; 404 "Value(s) not found" → pendente;
  HTML → `indisponivel` com o endpoint ainda respondendo 200; consulta > 10 anos fatiada; mês em
  cache não é buscado de novo. Validação manual: jul/26 = 1,2152% e ***% do CDI.

**Bloco 5 — APIs de extratos e aposentadoria do SnapshotMensal**
- `app/tools/extrato_lote.py`, `app/api/extrato_lote.py`; `app/api/extrato.py` (resumo
  enriquecido, DELETE, `/lancamentos`); `excluir_mes`; fim de `snapshot_do_extrato`; fim do
  `POST /snapshots`; `ultimo_fechamento` no dashboard.
- Pronto: matriz de status coberta; confirmar não altera `Posicao`; revalidação na confirmação;
  409 no mais recente; nenhum `SnapshotMensal` gravado; payload sem padrão de dado pessoal.

**Bloco 6 — Tool e system prompt**
- `tool_desempenho_carteira`; `app/tools/schemas.py`; `app/agent/loop.py`;
  `frontend/src/lib/tools.ts`; `docs/system_prompt_consultor_otimizado.md` (tabela de tools,
  princípio "rentabilidade vem de `desempenho_carteira`, nunca de variação de saldo", CDI/IPCA do
  mesmo período, tela Histórico arquiva meses antigos sem passar pelo chat).
- Pronto: saída < 2,5 KB; sem arquivos → `tool_error`.

**Bloco 7 — UI: casca do Histórico, aba Desempenho, painel Carteira**
- `App.tsx` (tela `chat | historico` espelhada em `location.hash`, rascunho no App, correção do
  `ModalImport`, fila de uma mensagem), `Sidebar.tsx`, `PainelCarteira.tsx` (sem câmera; série e
  delta a partir do histórico de extratos; atalho), `Sparkline.tsx`, `lib/api.ts`,
  `lib/format.ts`, `lib/graficos.ts`, `components/historico/*`.
- Pronto: `npm run build` limpo; QA em 375 px e no desktop.

**Bloco 8 — UI: aba Extratos**
- Lista, detalhe do mês, tabela de lançamentos com classificação, regras, lote, exclusão.
- Pronto: build limpo; QA com os arquivos de `uploads/`.

**Deploy A** (Blocos 0–8; só com confirmação do dono).

**Bloco 9 — Composição, comparação e CSV (backend)** · **Bloco 10 — UI correspondente e tool com
`nivel`** · **Bloco 11 — Documentação e Deploy B** — detalhes nas seções acima.

## Deploy e rotina pós-deploy

1. Backup de produção antes de cada deploy (passo 8 do `docs/PLANO_DEPLOY_FLY.md`).
2. `fly deploy`: o `create_all` cria `regralancamento`, `indicadormensal` e
   `referenciacarteira`; a semente grava o corte. Nenhuma coluna nova, nenhum script de migração.
3. Validar `/health/live`, login, Histórico vazio e `GET /desempenho` 200 com
   `benchmarks.status = ok`.
4. Rotina do dono **em produção** (nunca subir o banco local, que está defasado): lote com os
   meses antigos (entram como histórico) → importar pelo chat os meses mais novos que a
   carteira, com "sim" → classificar as pendências na aba Extratos → conferir a rentabilidade
   e o % do CDI de um mês conhecido contra o app do BTG.
   **Como ficou no deploy de 06/10:** o dono já tinha importado setembro pelo chat em 05/10
   (código antigo), então o corte nasceu em 2026-09-30 e setembro está arquivado sem o razão
   da conta. A rotina vira um lote só: jan–set/26 — de janeiro a agosto entram como "novo";
   setembro como "reenvio do mês atual", que completa os lançamentos e mascara o nome do
   arquivo guardado pelo código antigo (era o número da conta). Nada pelo chat até o extrato
   de outubro.
5. Rollback: a imagem anterior convive com as tabelas novas e com payload v2. O staging do lote
   vive em RAM: suspensão preserva, deploy ou restart descarta (a UI pede reenvio).

## Riscos

| Risco | Mitigação |
|---|---|
| Textos de débito, transferência, liquidação e Tesouro desconhecidos | vocabulário real mapeado; NAO_CLASSIFICADO + regras do dono; só a fronteira externo/interno afeta o total |
| Sinal dos débitos | sinal pela diferença de saldo + conferência do razão |
| Transferência de custódia entra sem fluxo e infla o retorno | pendência por ativo + regra `ativo_mes` |
| Nome de contraparte em linha de tipo desconhecido | lista de permissão nas transferências, máscara numérica, teste de privacidade |
| BTG reapresenta o mês anterior | aviso de continuidade; vale o V_ini do próprio extrato |
| BCB fora do ar ou mudando formato | cache permanente de meses fechados; `indisponivel`; endpoint sempre 200 |
| Dietz com fluxo grande | aviso `fluxo_relevante` |
| Descrição quebrada em duas linhas encerra a tabela | a conferência do razão acusa |

## Fora do escopo

Ibovespa/IFIX; valorização intramensal ou TWR diário; retorno líquido de IR; outras corretoras;
guardar o XLSX; editar posições de meses passados; proventos por ativo em competência;
biblioteca de gráficos; testes de frontend.

## Onde a execução divergiu do plano

- **Exclusão (409):** protege o mês do **corte** (`data_de_corte`), não "o arquivado mais
  recente". Com `ReferenciaCarteira`, apagar um mês antigo nunca abaixa o corte; o que não pode
  sumir é o mês que a carteira reflete. Em produção (corte em 2026-08-10, sem arquivo dessa
  data), julho pode ser apagado — com a regra antiga, não poderia, sem motivo.
- **Regras padrão:** além do previsto, crédito de "juros" e "cupom" em qualquer posição da
  descrição viram PROVENTO — é renda numa conta de investimento (JCP, cupom de título).
- **Benchmarks:** uma segunda tentativa em erro de transporte (timeout, conexão). A SGS falha
  de forma passageira com frequência; sem isso, metade das cargas da página perdia o IPCA.
- **Nome do arquivo:** mascarado já no upload (`POST /extrato/upload` e lote), não só no
  arquivamento — o nome é o número da conta e ia para o preview do agente e para os logs.
- **Bug antigo achado no Bloco 6 — o modelo não recebia o system prompt.** `_fixed_part()`
  cortava o .md no primeiro `=== CONTEXTO DINÂMICO ===`, que é a citação do marcador na nota
  "Como usar" da linha 3. De 06/2026 a 10/2026 a parte fixa enviada tinha 101 caracteres —
  sem persona, guardrails nem princípios das tools. Corrigido (o marcador só conta sozinho
  na linha) e coberto por teste. Como a parte fixa tem ~6 mil tokens e cada iteração do loop
  a reenvia, o system prompt passou a ir em blocos com **cache de prompt** (`cache_control`
  na parte fixa; tools entram no mesmo prefixo) e o custo do turno conta gravação (1,25×) e
  leitura (0,1×) do cache.
- **Proventos por classe não são empilhados.** O validador de paleta (método de dataviz)
  reprova vizinhos que aparecem quando uma classe intermediária falta — FIIs ao lado do
  Tesouro (visão normal ΔE 11,6) e ETFs ao lado do Tesouro (daltonismo ΔE 1,6). Como as cores
  das classes não podem mudar, a renda mensal é uma série só e a divisão por classe vai para
  uma lista de barras separadas, cada uma com rótulo.
- **Cores da aba Desempenho:** a carteira é a tinta clara (`ink`) e CDI/IPCA são cinza, com
  tracejado no IPCA; as cores categóricas ficam só para as classes (o azul é das Ações).
- **Rotas novas** leem `app.database.engine` na hora da chamada (não importam `engine` no
  carregamento), para que os testes troquem o banco num lugar só.
- **Composição (Bloco 9):**
  - preço unitário do papel = saldo ÷ quantidade, não a coluna de preço: é o mesmo número sem
    o arredondamento da coluna, e mantém o % coerente com o resultado em R$;
  - desdobramento só é reconhecido sozinho se, desfeito o fator, o preço fica mais perto do
    anterior do que sem desfazer — 10 ações a mais com o preço parado é transferência, não
    bonificação, e vira pendência;
  - título que cresce sem lote no mês: pendência no arquivo v2; no v1 (sem lotes) fica
    "indisponível" — regra não resolve, reenviar o XLSX resolve;
  - "evento societário" declarado num papel que surgiu ou sumiu (troca de ticker,
    incorporação) deixa o papel sem número no mês: esse caso não é modelado;
  - aporte/resgate em ativos é avaliado ao preço de fechamento, no último dia do mês (peso 0
    no Dietz): o papel transferido não ganha nada no mês da transferência;
  - classe sem percentual quando a base do Dietz fica abaixo de 25% do seu tamanho
    (`base_pequena`: classe que entra ou sai no mês) — o resultado em R$ continua;
  - a conferência soma também lançamentos `OUTRO_INTERNO` e renda que nenhum papel explica;
    linha não classificada fica de fora (se for aporte, o resíduo acusa) e o resíduo só é
    calculado quando todo papel do mês tem número;
  - a janela `inicio` da composição começa no primeiro extrato arquivado (a do total começa no
    primeiro mês com rentabilidade): a composição de um papel não depende do razão;
  - `ativo_ref` (em `lancamentos.py`) atribui a linha do razão ao papel pelo ticker ou pelo
    ano de vencimento + sigla/nome do título; o nome mais longo vence e ambiguidade não
    atribui. Resgate que não cita título casa com o único título que encolheu;
  - `/extrato/comparar` traz também os papéis mantidos (só variação de preço) e o caixa nas
    classes; o CSV "ativos" tem uma linha por mês e papel, pronta para tabela dinâmica.
- **Composição na tela (Bloco 10):**
  - o card "De onde veio o resultado" segue o filtro de período da aba e tem um atalho
    "Último mês"; a pendência de quantidade se resolve ali mesmo, com um botão por resposta
    (desdobramento/grupamento, veio de outra corretora, foi para outra corretora) — a
    transferência recarrega também o total, porque vira aporte ou resgate;
  - no mês em que um papel está pendente, o resultado da classe é a soma dos papéis que têm
    número (bate com a tabela por ativo) e o percentual da classe fica em branco;
  - "Comparar dois meses" fica na aba Extratos (padrão: os dois fechamentos mais recentes);
    os papéis que só mudaram de preço vêm recolhidos;
  - `fmtQtde` e `fmtPP` passaram a usar vírgula decimal ("0,12", "-0,3 p.p.") — muda também
    a tabela da carteira; o cabeçalho dos cards quebra em telas estreitas;
  - tool com `nivel=ativo`: para caber em 3 KB, a série `mensal` deixou de listar os meses sem
    extrato (já estão em `periodo.faltantes`) e os avisos agrupam meses seguidos
    ("ago/25–mai/26").

## Vocabulário observado (Bloco 0)

Registro **só de padrões genéricos** — nunca nome, CPF, conta ou descrição inteira. Gerado com
`scripts/inspecionar_extrato.py`.

**Extrato de 07/2026** (o único disponível em 05/10/2026):
- Razão da conta: `rendimentos` (3, créditos), `juros s/ capital` (1, crédito), `saldo final +
  rendimento provisionado` (1, crédito de centavos). Linha "Saldo Anterior" sem movimentação.
  Totais "Total de Créditos" / "Total de Débitos" (débitos vazios = `-`). Conferência fecha.
- RV: transações `JUROS S/CAPITAL` (Ações), `RENDIMENTO` (Fundos Listados), `EMPRESTIMO`
  (Ações | Aluguel). Sem compra nem venda no mês.
- RF: 8 lotes de Tesouro (LFT, LTN, NTNB-P), nenhum adquirido no período.
- Valores em trânsito: `juros s/ capital`.

**Pendente:** meses com TED/PIX, compra/venda de ações, aplicação/resgate e cupom de Tesouro.
Perguntas a responder quando chegarem: sinal dos débitos; texto de TED/PIX e se trazem nome ou
CPF; liquidação de bolsa por operação ou por dia, com ou sem ticker; aplicação, resgate,
vencimento e cupom de Tesouro trazem o título?; linhas de IR, IOF e custódia; transações de RV
(compra, venda, bonificação, subscrição, transferência); operação nos dois últimos pregões;
descrição quebrada em duas linhas; Sumário anterior de M = atual de M−1?; períodos sempre
mensais?
