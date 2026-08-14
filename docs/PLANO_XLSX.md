# Plano — Migração do import para XLSX (fonte única de verdade)

> ## ✅ EXECUTADO em 2026-08-05 — todos os 8 blocos concluídos
>
> 34 testes verdes. Extrato real 07/2026: 15/15 posições, R$ ***, checksum ok.
> **Nada foi commitado** — a working tree tem também as Fases 4–5 pendentes de commit
> (ver [PLANO_CORRECOES.md](PLANO_CORRECOES.md) Bloco 0).
>
> **Onde a execução divergiu do plano (e por quê):**
> - **Tolerância do checksum: R$ 0,05 → R$ 1,00.** O extrato real diverge R$ 0,11 sozinho —
>   o Saldo Bruto de RV do Sumário (***) não bate com a soma das próprias linhas de
>   posição (***). Com 0,05 todo import legítimo dispararia alarme falso. Ver o
>   comentário em `btg_xlsx_parser.py`.
> - **Bloco 6a: escolhida a via das colunas novas**, não o campo `notas`. `vencimento` e
>   `taxa_contratada` viraram colunas de `Posicao`, com `scripts/migrate_posicao_rf.py`
>   (idempotente, faz backup em `backups/` antes de alterar). `custo_total` ficou só no
>   preview — é derivável de `preco_medio × quantidade`.
> - **`sem_alvo_definido` também em `proposta_rebalanceamento`**, além de `calcular_desvio`:
>   o CAIXA é novo na carteira e apareceria como "+0,6 p.p. acima do alvo 0%" no what-if.
> - **Gap novo (G7), não previsto:** o endpoint público do Tesouro Direto passou a responder
>   **403** (não é o User-Agent — testado com UA de browser e sem UA). Nenhum título recebe
>   preço ao vivo hoje; todos caem para o saldo do extrato, que é a degradação prevista no
>   §6.7 do PLANO. O casamento do G4 está implementado e testado, mas não pôde ser validado
>   contra a fonte ao vivo. **O Tesouro Transparente (CKAN) responde 200** — migrar para lá
>   é decisão do dono, não executada.
> - **Extras de baixo risco:** removida a linha morta `pos_extrato` em `desvio.py` (Bloco 2
>   do PLANO_CORRECOES) e `scripts/test_fase2.py` foi adaptado ao fluxo de upload.
>
> ---

> **Contexto original do plano.** Autossuficiente: contexto, guardrails, mapeamento do
> arquivo e blocos de trabalho na ordem. Gerado em 2026-08-04 após inspeção do arquivo real
> `001234567.xlsx` (extrato BTG de 07/2026). Guardrails gerais do projeto: ver
> [PLANO_CORRECOES.md](PLANO_CORRECOES.md) §1 — continuam valendo integralmente.

---

## 0. Contexto e decisão

**A decisão do dono:** o extrato da conta de investimento do BTG agora é gerado em **XLSX**.
A partir de agora **o XLSX é a única fonte de verdade** para importação de posições.
**O caminho do PDF (colagem de texto) é aposentado** — não fica como fallback.

**Por que isso é uma melhora, não só uma troca de formato.** O XLSX carrega dados que o PDF
não dava e que o parser de texto jamais teria:

| Dado novo | Onde está | Para que serve |
|---|---|---|
| Custo de aquisição real do Tesouro, por lote | aba `Renda Fixa`, blocos `Detalhamento >` | `preco_medio` correto (hoje o Tesouro grava o preço *atual* como se fosse custo) |
| Taxa contratada (`SELIC + 0,10%`, `IPCA + 7,62%`, `13,03% a.a.`) | `Renda Fixa`, coluna *Taxa Média Ponderada* | análise real de RF; hoje inexistente no sistema |
| Vencimento exato (`2031-03-01`) | `Renda Fixa` | prazo/duration e casamento robusto com o TesouroProvider (resolve o **G4**) |
| Totais do mês anterior e do mês atual | aba `Sumario` | **checksum do import** e comparativo mensal |
| Proventos do mês (JCP, rendimentos de FII) | `Renda Variavel`/`Conta Corrente`, blocos `Movimentação >` | renda passiva do mês, comentável no preview |
| Saldo em conta corrente | aba `Conta Corrente` | posição de **CAIXA** (hoje ausente da carteira) |
| Aluguel de ações (doador) | `Renda Variavel`, `Posição > Ações \| Aluguel` | informativo — **cuidado para não duplicar** |

**Decisões já tomadas pelo dono (não reabrir):**
1. **Conta Corrente** vira posição `CAIXA`. **Valores em Trânsito** ficam **apenas informativos**
   no preview (ainda não liquidaram) — não entram na carteira.
2. **Custo médio ponderado do Tesouro** vem da aba de Detalhamento (lote a lote). Corrige o
   `preco_medio` do Tesouro, que hoje é o preço atual.
3. **Movimentações (proventos, aluguel) não são persistidas** — aparecem no preview do import
   para o agente comentar, e só. Sem tabela nova, sem migração de schema por conta disso.

---

## 1. Guardrails específicos deste plano

Além dos 10 guardrails da §1 do [PLANO_CORRECOES.md](PLANO_CORRECOES.md):

1. **O XLSX é binário — ele NUNCA entra no contexto do modelo.** O arquivo é parseado no
   servidor; o modelo vê apenas o **preview JSON** já estruturado. Nada de base64 no chat.
2. **A separação preview → confirmação → gravação continua intacta.** `importar_extrato`
   segue sendo read-only e `gravar_posicoes` continua sendo a única escrita, num turno
   posterior ao "sim". A mudança é *como o dado chega ao parser*, não o protocolo de escrita.
3. **Checksum obrigatório.** O total das posições parseadas é conferido contra os totais da
   aba `Sumario`. Divergência acima de R$ 0,05 → o preview traz `aviso` explícito com os dois
   números. **Avisar, não bloquear** (regra do PLANO §8.1). Isto é antialucinação aplicada ao
   import: se o parser perdeu uma linha, o usuário fica sabendo.
4. **Linha não reconhecida nunca é silenciada.** Toda linha dentro de um bloco de Posição que
   o parser não conseguir interpretar entra em `linhas_ignoradas` no retorno. Parser que come
   posição em silêncio é pior que parser que falha.
5. **O arquivo contém dados pessoais** (nome, CPF, agência/conta). Não commitar, não logar
   conteúdo de célula em log de nível INFO, não persistir o binário sem necessidade.

---

## 2. Mapeamento do arquivo real (`001234567.xlsx`, 07/2026)

Sete abas: `Capa`, `Sumario`, `Renda Fixa`, `Renda Variavel`, `Conta Corrente`,
`Valores em Trânsito`, `Fale Conosco`.

**Padrão estrutural (vale para todas as abas):** a coluna A é vazia; o conteúdo começa na
coluna B. Um bloco é aberto por uma célula-título do tipo `Posição > Ações`,
`Posição > TESOURO DIRETO - LFT`, `Detalhamento > TESOURO DIRETO - NTNB-P`,
`Movimentação > Ações`. A **linha seguinte é o cabeçalho** e as linhas seguintes são dados,
até uma linha cuja primeira célula começa com `Total`.

**Não posicionar por índice fixo de linha/coluna.** Localizar blocos pelo título e mapear
colunas **pelo cabeçalho** (normalizado). O layout muda com o conteúdo do mês (um mês sem
FII não terá o bloco de FIIs; um mês com CDB terá um bloco novo).

### 2.1 `Capa`
```
Extrato da Conta Investimento
Período de 01/07/26 a 31/07/26     → data_referencia = 2026-07-31 (fim do período)
Emitido em 04/08/26 23:29
*** / Banco: BTG Pactual / Conta Controle: 001234567 / CPF: ...
```
`data_referencia` sai do **fim do período**. Se a linha não casar, o import falha com
`tool_error` — não inventar data (guardrail 1 do projeto).

### 2.2 `Sumario` — checksum
Colunas: `Mercados | Saldo Bruto 30/06/26 | Saldo Líquido 30/06/26 | Saldo Bruto 31/07/26 | Saldo Líquido 31/07/26`.
Linhas: Renda Variável `25727,00` · Renda Fixa `18888,87` · Conta Corrente `***` ·
Valores em Trânsito `***` · **Total `44945,77`**.

Os rótulos das colunas de data **mudam todo mês** → identificar as colunas do mês corrente
como as **duas últimas**, não por texto de data.

Conferência esperada: `Σ(ações+ETF+FIIs) = ***` ≈ RV do sumário (arredondamento de
centavo é normal — daí a tolerância); `Σ(Tesouro) = ***` = RF; `CAIXA = ***`.

### 2.3 `Renda Variavel`
- `Posição > Ações` → `Código | Ação | Qtde. | Preço Fechamento R$ | Preço Médio R$ | Saldo Bruto R$`
  (5 papéis; nomes vêm com espaços múltiplos: `BRASIL      ON      NM` → colapsar whitespace).
- `Posição > ETF` → mesmas colunas (IVVB11).
- `Posição > Fundos Listados` → tem coluna extra `Tipo` (`FII`) entre nome e quantidade.
- `Posição > Ações | Aluguel` → **NÃO é posição.** TAEE11 aparece aqui como doador
  (R$ ***) **e** na posição de Ações (R$ ***). Somar os dois duplica o papel. Ler apenas
  como informativo (`aluguel_ativo: [...]`) no preview.
- `Movimentação > Ações` e `Movimentação > Fundos Listados` → proventos do mês
  (JCP ITUB4 R$ 0,71 líq.; rendimentos KNCR11/HGCR11/RBRR11 = R$ ***). Informativo.

### 2.4 `Renda Fixa`
- `Posição > TESOURO DIRETO - {LFT|LTN|NTNB-P}` → `Emissor | Ativo | Emissão | Vencimento |
  ... | Taxa Média Ponderada | Quantidade | Preço R$ | Saldo Bruto R$ | IR R$ | IOF R$ | Saldo Líquido R$`.
  **A posição consolidada sai daqui.** Cinco títulos: LFT 2031, LFT 2028, LTN 2028, LTN 2029,
  NTNB-P 2029.
- `Detalhamento > TESOURO DIRETO - X` → **um lote por linha de aquisição**, com
  `Preço Compra R$` e `Valor Compra R$`. A NTNB-P 2029 tem 4 lotes (R$ *** de custo total
  para R$ *** de saldo bruto). **Fonte do custo médio ponderado.**
- `Posição Consolidada Por Emissor` → só conferência (`BACEN... ***`).

**Generalidade:** o bloco é `Posição > <TIPO>` com um emissor por linha. Emissor
`BACEN-BANCO CENTRAL DO BRASIL - RJ` → classe `TESOURO`; **qualquer outro emissor** (um CDB
futuro) → classe `RF`, ticker `None`, nome `"<Tipo> <Emissor> <vencimento>"`. Hoje não há
nenhum no extrato, mas o parser não pode ignorar o bloco — cairia no guardrail 4 da §1.

**Armadilhas numéricas:** quantidade do Tesouro é **fracionária** (`0,12`; `5,69`) — nada de
regex `\d+`. Preço é o **preço unitário do título** (`***` para a LFT). Células vazias
vêm como `None` e valores nulos como a string `"-"`.

### 2.5 `Conta Corrente` e `Valores em Trânsito`
- `Conta Corrente` / `Posição` → `Data | Valor financeiro R$` → `2026-07-31 | ***` →
  posição `CAIXA`, nome `"Conta corrente BTG"`, ticker `None`, quantidade `1`,
  `valor_mercado = ***`.
- `Valores em Trânsito` → 3 JCP a liquidar (R$ ***). **Informativo.**
- O nome da aba tem acento (`Trânsito`): localizar aba por **nome normalizado**
  (`unicodedata.normalize` + casefold), nunca por igualdade literal.

### 2.6 Tipos
`openpyxl` com `data_only=True` devolve **datas como `datetime`** e **números como `float`**
— não como texto brasileiro. O helper `_br()` do parser antigo **não se aplica**; o novo
conversor precisa aceitar `float`/`int`/`datetime`/`"-"`/`None`/string com vírgula (o BTG
pode mudar isso a qualquer release).

---

## 3. Arquitetura da mudança

O ponto de design mais importante: **XLSX não pode trafegar pelo chat.** Hoje o fluxo é
`usuário cola texto na UI → texto vai na mensagem → modelo chama importar_extrato(texto)`.
Com binário isso é impossível (e mesmo em base64 seria desperdício absurdo de contexto).

**Fluxo novo:**

```
UI (input file)  ──POST /extrato/upload (multipart)──►  parser XLSX (servidor)
                                                              │
                                                     preview em staging (memória)
                                                              │
UI envia ao chat: "importe o extrato que acabei de subir"      │
                          │                                    │
                   modelo chama importar_extrato()  ◄──────────┘  (sem argumentos)
                          │
                   preview JSON no chat  →  usuário: "sim"  →  gravar_posicoes(posicoes)
```

- O **upload** só parseia e guarda o preview. Não grava posição nenhuma (guardrail 4).
- O **staging** é um módulo-level singleton em memória (`app/tools/extrato_staging.py`):
  `{preview, arquivo_nome, recebido_em}`. Single-user local, um processo — não precisa de
  tabela. Reiniciar o servidor limpa o staging; a tool responde
  `tool_error("Nenhum extrato foi enviado — use o botão 'Importar extrato' na UI.")`.
- **O binário não é persistido em disco** por padrão (contém CPF). Se um dia quiser
  reprocessar, salvar em `uploads/` — já está no `.gitignore`.
- `importar_extrato()` passa a **não ter argumentos**: lê o staging e devolve o preview.
  Continua read-only.
- `gravar_posicoes()` passa a **não ter argumentos**: lê o preview do staging (valores
  exatos, sem o modelo redigitar número) e trata o extrato como a carteira completa —
  posição ativa fora do lote é desativada e volta em `posicoes_desativadas`.
  O upsert casa por `chave_externa` (`B3:BBAS3`, `TD:LFT:2031-03-01`,
  `RF:<emissor>:<sigla>:<vencimento>`, `CAIXA:BTG`), com fallback ticker → nome para as
  linhas anteriores à migração. Casar por nome não serve: o BTG reescreve o nome entre
  extratos (`FII HGCR PAXCI` → `FII HGCR PAXCI ER`).

---

## 4. Blocos de trabalho (fazer nesta ordem)

| Bloco | O quê | Risco | Depende de |
|---|---|---|---|
| **0** | Privacidade: `.gitignore` do extrato | nenhum | — |
| **1** | Parser XLSX + testes (fixture anonimizada) | médio | 0 |
| **2** | Upload REST + staging | baixo | 1 |
| **3** | Tool `importar_extrato` sem args + schema + dispatch | baixo | 2 |
| **4** | UI: input file no lugar do textarea | baixo | 2 |
| **5** | Aposentar o caminho PDF | baixo | 3, 4 |
| **6** | Custo do Tesouro no banco + G4 (casamento por vencimento) | médio | 1 |
| **7** | Docs (PLANO, system prompt, README) | nenhum | todos |

---

### Bloco 0 — Privacidade (fazer antes de qualquer `git add`)

`001234567.xlsx` está **untracked na raiz do repo** e contém nome, CPF e número de conta.
Um `git add .` distraído o commita.

1. Adicionar ao `.gitignore`:
   ```
   # Extratos (dados pessoais — nome, CPF, conta)
   *.xlsx
   *.xls
   uploads/
   ```
   (`uploads/` já está lá — confirmar.)
2. Mover o arquivo para `uploads/001234567.xlsx` (fora da raiz, já ignorado) e usar esse
   caminho no desenvolvimento.
3. Confirmar que nunca foi commitado: `git log --all --oneline -- '*.xlsx'` deve sair vazio.
   (Verificado em 2026-08-04: `git ls-files | grep xlsx` vazio — está limpo.)

**Commit:** `chore: ignorar extratos XLSX (dados pessoais) no git`

---

### Bloco 1 — Parser XLSX (`app/tools/btg_xlsx_parser.py`)

Novo módulo, espelhando o contrato do `btg_parser.py` atual: devolve `list[PosicaoParsed]`
mais os metadados novos. **Reaproveitar o dataclass `PosicaoParsed`** movendo-o para o módulo
novo (ou para um `parser_types.py`) e **estendendo** com campos opcionais:
`vencimento: Optional[str]`, `taxa_contratada: Optional[str]`, `custo_total: Optional[float]`.

**Assinatura sugerida:**
```python
def parse_btg_xlsx(conteudo: bytes) -> ExtratoParsed
```
onde `ExtratoParsed` carrega: `posicoes`, `data_referencia`, `sumario` (dict por mercado,
mês anterior e atual), `proventos`, `aluguel`, `valores_em_transito`, `linhas_ignoradas`,
`checagem` (resultado do checksum).

**Helpers obrigatórios:**
- `_num(v)` → `float | None`, aceitando `float`, `int`, `"-"`, `None`, `"1.234,56"`.
- `_data(v)` → `str | None` (ISO `YYYY-MM-DD`), aceitando `datetime` e `dd/mm/aa`.
- `_norm(s)` → minúsculo, sem acento, whitespace colapsado — para casar nomes de aba,
  títulos de bloco e **cabeçalhos de coluna**.
- `_blocos(ws)` → itera `(titulo, cabecalho, linhas)` pelo padrão descrito na §2.

**Ordem de leitura:** `Capa` (data_referencia; falhar se ausente) → `Sumario` → `Renda Variavel`
→ `Renda Fixa` (Posição, depois Detalhamento para o custo) → `Conta Corrente` →
`Valores em Trânsito` → checksum.

**Regras de negócio a implementar:**
- Ticker do Tesouro: `f"{_TESOURO_NOME[sigla]} {ano_do_vencimento}"` — reaproveitar o mapa
  `_TESOURO_NOME` do parser antigo. Com o vencimento exato agora disponível, guardar também
  `vencimento` ISO completo.
- Agregar Tesouro por `(sigla, vencimento)` — defesa contra duas linhas do mesmo título com
  emissões diferentes.
- Custo médio ponderado: `Σ(Valor Compra) / Σ(Quantidade)` dos lotes do Detalhamento, casados
  por `(sigla, vencimento)`. Guardar `custo_total` também. **Sem Detalhamento no arquivo →
  `preco_medio = None`**, nunca o preço atual disfarçado de custo.
- Aluguel: ler para `aluguel`, **jamais** para `posicoes`.
- CAIXA: uma posição, `nome="Conta corrente BTG"`, `classe="CAIXA"`, `ticker=None`,
  `quantidade=1.0`, `preco_medio=None`.
- Checksum (§1.3): comparar RV / RF / CAIXA e total contra o `Sumario`.

**Testes (`tests/test_btg_xlsx_parser.py`) — obrigatórios neste bloco:**
Criar `tests/fixtures/extrato_exemplo.xlsx` = **cópia anonimizada** do real (trocar nome, CPF
e conta por valores fictícios; manter números e estrutura intactos). Essa fixture *pode* ser
commitada — a real, não. Cobrir:
1. 9 posições de RV+RF (5 ações, 1 ETF, 3 FIIs, 5 Tesouro → 14) + 1 CAIXA = **15 posições**;
2. total = `***` e checksum sem aviso;
3. `data_referencia == "2026-07-31"`;
4. TAEE11 aparece **uma única vez** (regressão do bug de duplicação por aluguel);
5. custo médio da NTNB-P 2029 = `*** / 1.92` ≈ `3400,61` (não `3797,08`);
6. arquivo inválido (bytes lixo / planilha sem as abas) → erro tratado, sem exceção.

**Critério de pronto:** `pytest tests/ -q` verde (3 antigos + os novos); parser roda no
arquivo real e as 15 posições batem com o Sumário.
**Commit:** `feat: parser XLSX do extrato BTG (posições, custo do Tesouro, caixa, checksum)`

---

### Bloco 2 — Upload REST + staging

**`app/tools/extrato_staging.py`** — store em memória:
`set_preview(preview, arquivo)`, `get_preview()`, `clear()`, com `recebido_em`
(`datetime.now(timezone.utc)` — guardrail 7).

**`app/api/extrato.py`** — espelhar o padrão de `app/api/posicoes.py`:
- `POST /extrato/upload` (`UploadFile`, multipart — `python-multipart` já está nas deps).
  Validar extensão `.xlsx` e tamanho (≤ 5 MB). Parsear, gravar no staging, **devolver o
  preview** para a UI já mostrar um resumo. Erro de parser → HTTP 400 com a mensagem.
- `GET /extrato/preview` → preview atual ou `404` se não houver.
- `DELETE /extrato/preview` → limpa o staging.

Registrar o router em [app/main.py](../app/main.py) junto dos outros (`include_router`).

**Critério de pronto:** `curl -F "arquivo=@uploads/001234567.xlsx" localhost:8000/extrato/upload`
devolve o preview com 15 posições; segundo upload substitui o primeiro.
**Commit:** `feat: endpoint POST /extrato/upload com staging em memória`

---

### Bloco 3 — Tool `importar_extrato` sem argumentos

1. **[app/tools/extrato.py](../app/tools/extrato.py)** — `tool_importar_extrato()` sem
   parâmetros: lê o staging; vazio → `tool_error(...)` pedindo o upload pela UI. Mantém o
   formato de retorno atual (`posicoes`, `total_posicoes`, `total_valor_mercado`,
   `data_referencia`, `resumo_por_classe`, `source`, `aviso`) e **acrescenta**
   `proventos_do_mes`, `aluguel_ativo`, `valores_em_transito`, `comparativo_mes_anterior`,
   `checagem_totais`, `linhas_ignoradas`.
   O `aviso` perde a nota sobre "RF privada não aparece no PDF" (no XLSX ela apareceria) e
   ganha, quando for o caso, o alerta de divergência do checksum.
2. **[app/tools/schemas.py](../app/tools/schemas.py)** — `importar_extrato` passa a
   `"properties": {}, "required": []`. Descrição nova: *"Lê o extrato XLSX do BTG que o
   usuário subiu pela UI e retorna o PREVIEW das posições — não salva nada."* Se não houver
   upload, a tool orienta o usuário a usar o botão.
3. **[app/agent/loop.py](../app/agent/loop.py)** — dispatch:
   `"importar_extrato": lambda _i: tool_importar_extrato()`.

**Critério de pronto:** no chat, "importe meu extrato" após um upload devolve o preview
completo; sem upload, devolve a orientação — e em nenhum dos casos algo é gravado.
**Commit:** `refactor: importar_extrato lê o XLSX enviado (sem argumento de texto)`

---

### Bloco 4 — UI: arquivo no lugar de texto

Em [static/index.html](../static/index.html), no modal `#import-panel`:
- Trocar `<textarea id="extrato-text">` por `<input type="file" accept=".xlsx">`.
- `#do-import` → `POST /extrato/upload` via `FormData`; com o preview de volta, mostrar um
  resumo curto (nº de posições, total, data de referência, aviso de checksum se houver) e
  então `sendMessage('Importe o extrato que acabei de enviar.')` — a mensagem no chat fica
  **curta**, sem despejar o extrato (some também a gambiarra de truncar mensagem longa na
  linha ~351).
- Erro do upload → mostrar a mensagem do backend no próprio modal, sem ir para o chat.
- Textos: "Importar extrato BTG (XLSX)"; instrução de onde baixar o arquivo no app do BTG.

**Critério de pronto:** selecionar o arquivo → preview aparece → "sim" no chat grava as
posições. O chat não contém nenhuma colagem gigante.
**Commit:** `feat: UI de import por upload de XLSX`

---

### Bloco 5 — Aposentar o caminho PDF

Decisão do dono: **XLSX é a única verdade**. Nada de dois caminhos vivos.

- **Remover** `app/tools/btg_parser.py` (o git guarda o histórico se um dia fizer falta).
- Remover o que ficou órfão: helper `_br`, mapa de seções, `_is_noise`, e a instrução de
  "Ctrl+A / Ctrl+C no leitor de PDF" onde aparecer.
- Buscar referências residuais antes de fechar: `grep -rn "parse_btg_text\|btg_parser\|PDF" app/ static/ docs/ tests/`.

**Critério de pronto:** nenhuma referência ao parser de PDF no código; testes verdes.
**Commit:** `refactor: remover parser de PDF — XLSX é a fonte única do extrato`

---

### Bloco 6 — Custo do Tesouro no banco + G4

**6a. Persistir os campos novos.** `preco_medio` do Tesouro passa a ser custo real, o que já
melhora tudo sem schema novo. `vencimento` e `taxa_contratada` **não têm coluna** em
[app/models/posicao.py](../app/models/posicao.py). Duas saídas:
- **Simples (recomendado para começar):** gravar em `notas`
  (`"venc. 2031-03-01 · SELIC + 0,10%"`). Zero migração.
- **Correto a médio prazo:** colunas `vencimento: Optional[datetime]` e
  `taxa_contratada: Optional[str]`. O projeto usa `SQLModel.metadata.create_all`, que **não
  altera tabela existente** → exige `scripts/migrate_add_rf_fields.py` com
  `ALTER TABLE posicao ADD COLUMN ...` idempotente (checar `PRAGMA table_info`) **e um backup
  antes** (Bloco 4 do [PLANO_CORRECOES.md](PLANO_CORRECOES.md)).

Escolher uma e seguir; não deixar as duas meio-feitas.

**6b. G4 fica trivial.** O gap G4 (casamento tolerante de nomes do Tesouro) existia porque o
PDF só dava o nome montado. Agora há `(sigla, vencimento exato)`. O `TesouroProvider` passa a
casar por **tipo + data de vencimento** — determinístico, sem heurística de texto.
Validar que os 5 títulos recebem preço ao vivo (`source=tesouro`) no `calcular_desvio`;
sem casamento, fallback para o extrato **com log de warning** (nunca falhar).

**6c. CAIXA no desvio.** Com uma posição `CAIXA` na carteira, conferir
[app/tools/desvio.py](../app/tools/desvio.py) e
[app/tools/rebalanceamento.py](../app/tools/rebalanceamento.py): a classe entra no
denominador do percentual e provavelmente **não tem alvo cadastrado** → garantir que aparece
como classe sem alvo (aviso), sem quebrar o cálculo nem virar "desvio de -100%".
Decidir com o dono se `CAIXA` ganha alvo próprio no seed — **fora deste plano**, mas o
comportamento não pode quebrar.

**Critério de pronto:** Tesouro com `preco_medio` = custo real e preço ao vivo do provider;
`calcular_desvio` roda com CAIXA na carteira sem erro nem número absurdo.
**Commit:** `feat: custo real e vencimento do Tesouro + G4 por vencimento exato`

---

### Bloco 7 — Documentação

- **[docs/system_prompt_consultor_otimizado.md](system_prompt_consultor_otimizado.md):**
  linha ~60 da tabela de tools → `importar_extrato()` sem argumento, "extrato **XLSX**
  enviado pela UI"; linha ~71 (fluxo de import) → "usuário sobe o XLSX na UI → você chama
  `importar_extrato()`". Acrescentar que o preview traz **proventos do mês** e o
  **checksum**, e que uma divergência de totais deve ser **dita ao usuário**, não engolida.
- **[PLANO.md](PLANO.md) §6.7 / §13:** import por XLSX substitui a colagem de PDF; registrar
  os dados novos (custo do Tesouro, taxa, vencimento, caixa, proventos).
- **[PLANO_CORRECOES.md](PLANO_CORRECOES.md) Bloco 5b:** anotar que **G4 foi resolvido por
  este plano** (Bloco 6b) — o casamento agora é por vencimento exato.
- **README.md:** como gerar o XLSX no BTG e como importar.
- **Memória do projeto:** atualizar `MEMORY.md` com "extrato = XLSX, PDF aposentado".

**Commit:** `docs: import por XLSX (system prompt, PLANO, README)`

---

## 5. Riscos conhecidos

1. **O BTG muda o layout do XLSX.** É o risco central de qualquer parser de arquivo de
   terceiro. Mitigação: casar por título de bloco e cabeçalho normalizado (nunca índice
   fixo), `linhas_ignoradas` sempre visível e checksum contra o Sumário — o import fica
   *ruidoso* quando quebra, em vez de silenciosamente errado.
2. **Classes novas aparecendo** (CDB, LCI, fundo). O parser precisa gerar `RF`/`FUNDO`
   genérico em vez de ignorar. Quando acontecer, validar com o extrato real do mês.
3. ~~**Reimportar o mesmo mês** — um ativo vendido continua no banco com o valor antigo;
   nenhum caminho marca posição ausente como `ativo=False`.~~ **Resolvido:** o import
   reconcilia o lote (posição fora do extrato vira `ativo=False`, listada em
   `posicoes_desativadas`) e o upsert casa por `chave_externa`, não por nome. O sintoma
   era a aba Carteira parecendo congelada: R$ 39,5 mil de posições de 06/2026 somando no
   dashboard depois de um import bem-sucedido.
4. **CAIXA sem alvo de classe** distorcendo o desvio — tratado no Bloco 6c.

## 6. Fora deste plano

- Persistir proventos/movimentações (decisão do dono: só preview).
- Incluir Valores em Trânsito na carteira.
- Marcar automaticamente como inativa a posição ausente do extrato novo (risco 3).
- Manter qualquer suporte a PDF.
- Alvo de classe para CAIXA no seed (só garantir que não quebra).
