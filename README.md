# Consultor de IA para Finanças

Agente consultor financeiro pessoal, **local** e single-user. Roda em `127.0.0.1:8000`,
é **estritamente consultivo** (nunca executa ordens) e **nunca inventa número**: todo dado
que chega a você vem de uma tool, com fonte e data.

Documento de arquitetura: [docs/PLANO.md](docs/PLANO.md).

## Rodar

```powershell
# Servidor
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Testes
.venv\Scripts\python.exe -m pytest tests/ -q
```

Abra `http://127.0.0.1:8000`. O banco fica em `data/carteira.db` (config em `app/config.py`).
A chave da API vai no `.env` (veja `.env.example`) — nunca no repositório.

## Frontend

A interface é um app React (Vite + TypeScript + Tailwind) em `frontend/`. O build sai em
`static/` e é servido pelo próprio FastAPI — **`static/index.html` e `static/assets/` são
gerados, não edite à mão**.

```powershell
cd frontend
npm install          # primeira vez

npm run build        # gera static/ — obrigatório após qualquer mudança na UI
npm run dev          # http://127.0.0.1:5173, hot reload, /api proxiada para a :8000
```

No modo `dev` o uvicorn precisa estar de pé na 8000 — o Vite encaminha `/chat`,
`/dashboard`, `/extrato` e as demais rotas para ele.

O chat consome `POST /chat/stream` (SSE): a resposta aparece token a token e a UI mostra
qual tool está rodando. `POST /chat` continua existindo, com a resposta inteira de uma vez,
para scripts e testes.

## Importar o extrato do BTG

O extrato **XLSX** é a única fonte de verdade das posições.

1. No BTG (web ou app): **Investimentos → Extratos → Extrato da Conta Investimento →**
   escolher o período → **exportar em XLSX**.
2. Na interface do consultor: botão **"Importar extrato BTG"** → selecionar o arquivo →
   **"Enviar extrato"**.
3. O agente mostra o preview (posições, totais, proventos do mês, conferência de totais).
   **Nada é salvo ainda.**
4. Responda **"sim"** no chat para gravar.

O que vira posição na carteira: ações, ETFs, FIIs, Tesouro Direto, renda fixa privada e o
saldo da conta corrente (classe `CAIXA`).

Se o total das posições não bater com o Sumário do próprio extrato, o preview avisa — vale
conferir antes de confirmar.

### Histórico e desempenho

A carteira (tabela `posicao`) guarda só o estado atual: o import sobrescreve quantidade e
valor de cada papel. Por isso cada confirmação também **arquiva o extrato do mês** em
`extratoimportado` — posições, proventos, movimentações, lotes de renda fixa, o razão da
conta corrente, sumário e conferências. É único por data de referência: reenviar o mesmo
XLSX **corrige** o mês, não duplica.

A tela **Histórico** (barra lateral) lê esse arquivo:

- **Desempenho** — rentabilidade mês a mês e acumulada (mês, ano, 12 meses, desde o início),
  **descontados aportes e resgates** (Modified Dietz sobre o patrimônio do extrato,
  encadeado), contra CDI e IPCA dos mesmos meses (BCB/SGS 12 e 433, guardados em
  `indicadormensal`); renda passiva; e "De onde veio o resultado", por classe e por ativo,
  com o mês a mês de cada papel. Exporta CSV para o Excel.
- **Extratos** — os meses arquivados, a conferência de cada um, os lançamentos da conta com a
  classificação (aporte, resgate, compra, provento...) e a comparação de dois meses.

**Aportes e resgates saem do razão da conta corrente.** PIX, TED e DOC são reconhecidos pelo
sinal; o que o classificador não reconhece fica "a classificar" e deixa o mês **provisório**
até você escolher o tipo na aba Extratos — a escolha vira regra (`regralancamento`) e vale
para os outros meses. Quantidade que muda sem compra nem venda (desdobramento, ativo trazido
de outra corretora) aparece como pendência no Desempenho.

**Meses antigos** entram de uma vez em **Extratos → "Enviar extratos antigos"** (até 24
XLSX). O lote só arquiva meses que **não mexem na carteira** — anteriores à data que ela
reflete (`referenciacarteira`). O mês mais novo continua entrando pelo chat, com o "sim"; e
um extrato antigo enviado pelo chat também só é arquivado, sem voltar a carteira no tempo.
Extratos arquivados antes da versão 2 do parser não têm o razão da conta: reenvie o XLSX
para calcular a rentabilidade deles.

No chat, o consultor responde perguntas de desempenho pela tool `desempenho_carteira`.

```
GET    /desempenho                            série, janelas, CDI/IPCA, renda passiva
GET    /desempenho/composicao?janela=12m      por classe e por ativo (mes, ano, 12m, inicio)
GET    /desempenho/ativo?chave=B3:BBAS3       um papel mês a mês
GET    /desempenho/export.csv?tipo=mensal     ou tipo=ativos
GET    /extrato/historico                     meses arquivados
GET    /extrato/historico/2026-07-31          o extrato completo daquele mês
GET    /extrato/historico/2026-07-31/lancamentos
DELETE /extrato/historico/2026-07-31          tira do histórico (o mês da carteira não sai)
GET    /extrato/comparar?de=2026-06-30&ate=2026-07-31
POST   /extrato/lote                          avalia vários XLSX — nada é gravado
POST   /extrato/lote/{id}/confirmar           arquiva os meses escolhidos
GET    /extrato/regras · POST /extrato/regras · DELETE /extrato/regras/{id}
```

`snapshotmensal` é legado: guarda as fotos manuais antigas (`GET /snapshots`), mas nada novo
é gravado lá e nenhum gráfico o usa. Plano e decisões: [docs/PLANO_HISTORICO.md](docs/PLANO_HISTORICO.md).

> **Privacidade:** o extrato contém nome, CPF e número da conta. `*.xlsx` está no
> `.gitignore` e o servidor não grava o arquivo em disco. Guarde os extratos em `uploads/`
> (também ignorado). O histórico arquivado guarda apenas o que o parser estruturou: as
> descrições de PIX e TED ficam só com palavras genéricas ("PIX RECEBIDO"), as demais têm
> CPF, CNPJ, conta e números longos mascarados, e o nome do arquivo (que é o número da
> conta) é mascarado já no upload.

## Backup e restauração

O banco é um único arquivo SQLite — é a carteira inteira.

```powershell
# Backup (método seguro, funciona com o banco em uso)
.venv\Scripts\python.exe -c "import sqlite3; o=sqlite3.connect('data/carteira.db'); d=sqlite3.connect('backups/carteira-manual.db'); o.backup(d); d.close(); o.close()"
```

**Restaurar:** pare o servidor e copie o arquivo de backup por cima de `data/carteira.db`.

A migração de schema (`scripts/migrate_posicao_rf.py`) faz backup automático em `backups/`
antes de alterar qualquer coisa.

## Deploy (Fly.io)

No ar em <https://consultor.fly.dev> — app `consultor`, org `kdu07`, região `gru`. O plano e
o registro do que foi feito estão em [docs/PLANO_DEPLOY_FLY.md](docs/PLANO_DEPLOY_FLY.md)
(§9). No dia a dia:

```powershell
fly deploy        # publica a versão local (builder remoto; não precisa de Docker local)
fly status        # deve haver sempre UMA máquina — SQLite + um volume não aceitam duas
fly logs          # logs ao vivo
```

**Backup do banco de produção:** passo 8 do plano (checkpoint + `fly ssh sftp get`).

**Autenticação:** com `APP_PASSWORD` preenchida, tudo exige um cookie de sessão assinado
(30 dias) — livres apenas `/`, `/static/*`, `/health/live` e as rotas de login. Vazia, o app
roda aberto, que é o modo local de sempre. Com `ENV=production` as duas variáveis
(`APP_PASSWORD` e `SESSION_SECRET`) são obrigatórias: sem elas o servidor não sobe.

**Antes de mandar o banco para o volume**, rode `uv run python scripts/preparar_db_para_upload.py`
— o SQLite roda em WAL e as últimas escritas moram no `-wal` até o checkpoint.

## Estrutura

| Pasta | O que tem |
|---|---|
| `app/agent/` | loop do agente (tool-use) e builder do system prompt |
| `app/api/` | endpoints REST (chat, posições, extrato, dashboard, health, ...) |
| `app/tools/` | as tools do agente — cada uma devolve `{dados, source, as_of}` ou `{error}` |
| `app/providers/` | fontes de preço (yfinance, brapi, Tesouro) |
| `app/models/` | tabelas SQLModel |
| `docs/` | PLANO.md (arquitetura), system prompt e planos de trabalho |
| `scripts/` | utilitários de manutenção e testes manuais contra o servidor |

> **Disclaimer:** conteúdo educacional/informativo. Não é recomendação de investimento.
> As decisões — e a responsabilidade por elas — são suas.
