# Plano de deploy no Fly.io — Consultor Financeiro Pessoal

Rev. 3 — 13/08/2026
Alternativa a `PLANO_DEPLOY_VERCEL.md` — este é o caminho recomendado.

> **O que mudou da rev. 2:** os Blocos A, B e C foram **implementados** — ver §8,
> "Estado da execução". O plano em si continua válido; as diferenças entre o que
> estava escrito e o que ficou no código estão listadas lá. O que falta é só a
> parte manual (§4, passos 1 a 10), que depende da sua conta no Fly.
>
> **O que mudou da rev. 1:** o plano foi conferido linha a linha contra o código atual.
> Três coisas estavam erradas e foram corrigidas: (a) `itsdangerous` **não** vem com o
> Starlette — é dependência nova e obriga um `uv lock`; (b) o `Dockerfile` copiava
> `static/` para dentro do estágio de build, onde o Vite apaga a pasta em seguida;
> (c) faltava `--ha=false` no primeiro deploy. O restante do plano foi confirmado
> como correto — ver §7, "O que foi verificado no código".

---

## 0. Por que este plano é curto

O Fly roda um contêiner de verdade, com disco de verdade, em processo permanente.
Isso apaga dois blocos inteiros do plano da Vercel:

| Premissa do projeto | Vercel | Fly.io |
|---|---|---|
| SQLite em `data/carteira.db` | migrar para Postgres | **fica como está**, num volume em `/data` |
| `_sessions` / `extrato_staging` em memória | mover para o banco | **ficam como estão** — processo único |
| `create_tables()` + `seed_all()` no lifespan | virar script externo | **fica como está** |
| Upload de 5 MB | baixar para 4 MB | **fica como está** |
| Sem autenticação | implementar | implementar (idem) |
| `yfinance`/Tesouro bloqueados por IP | contornar com brapi | região `gru` → **IP em São Paulo** |

Sobra: escrever `Dockerfile` + `fly.toml`, implementar autenticação, e ajustar meia dúzia
de detalhes pequenos. Meio dia de trabalho, contra ~2 dias na Vercel.

Bônus relevante: com `auto_stop_machines = "suspend"`, o Fly tira um snapshot Firecracker
da VM inteira — **incluindo a RAM**. A máquina ociosa é suspensa, para de custar CPU, e
volta em algumas centenas de ms *com o histórico do chat e o staging do extrato
intactos na memória*. O modelo mental do código (processo único, singleton, estado em
RAM) sobrevive sem uma linha de mudança.

Com uma ressalva honesta: o suspend preserva a RAM entre uma suspensão e a retomada,
**não** entre deploys nem entre reinícios. Todo `fly deploy` e todo `fly secrets set`
zeram `_sessions` (histórico do chat) e `extrato_staging`. É o mesmo comportamento de
hoje, quando você reinicia o uvicorn — o código já trata: o staging manda subir o
arquivo de novo, e o chat começa uma conversa nova.

---

## 1. Arquitetura alvo

```
GitHub  →  fly deploy  →  App "consultor" (região gru / São Paulo)
                             ├── 1 Machine shared-cpu-1x, 512 MB
                             │     └── uvicorn app.main:app  (FastAPI + SPA em /static)
                             └── 1 Volume "consultor_data" 1 GB → /data/carteira.db
```

- Uma única máquina, um único volume. É o certo aqui: SQLite não aceita dois
  processos gravando, e um volume só monta numa máquina por vez.
- O frontend é buildado no próprio `Dockerfile` (multi-stage) e servido pelo FastAPI
  em `/static`, exatamente como já acontece localmente.
- TLS e domínio `*.fly.dev` são automáticos; IPv4 compartilhado e IPv6 são gratuitos.
- `auto_stop_machines = "suspend"` + `min_machines_running = 0`: ociosa, ela dorme.

---

## 2. Mudanças de código (eu faço)

### Bloco A — Empacotamento

**`Dockerfile`** (novo, multi-stage):

```dockerfile
# --- estágio 1: build do frontend ---
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package*.json frontend/
RUN npm ci --prefix frontend
COPY frontend/ frontend/
RUN npm run build --prefix frontend     # tsc -b && vite build → escreve em ../static

# --- estágio 2: runtime ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ app/
COPY docs/ docs/
COPY --from=frontend /build/static/ static/
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Três detalhes que valem explicação, porque cada um deles quebra o build se sair errado:

1. **Nada de `COPY static/ static/` no estágio 1.** A rev. 1 fazia isso, e era pior que
   inútil: `vite.config.ts` tem `outDir: '../static'` com `emptyOutDir: true`, ou seja,
   o Vite **apaga** a pasta antes de escrever. Todo o conteúdo de `static/` hoje é saída
   do Vite (`index.html` + `assets/`), então não há nada ali para preservar.
2. **`docs/` precisa ir para a imagem.** `app/seeds.py:19` lê
   `docs/perfil_risco_investidor.md` e `app/agent/system_prompt.py:20` lê
   `docs/system_prompt_consultor_otimizado.md`, ambos por `Path(__file__).parent…`
   ancorado na raiz do projeto. Com `WORKDIR /app` e o pacote em `/app/app`, a raiz
   resolvida é `/app` e os arquivos caem em `/app/docs` — confere.
3. **`uv sync --frozen` usa o `uv.lock` como está.** Se o lock estiver desatualizado em
   relação ao `pyproject.toml`, a dependência nova simplesmente não é instalada e o erro
   só aparece em runtime, como `ImportError`. Como o Bloco C acrescenta `itsdangerous`,
   é obrigatório rodar `uv lock` e commitar o `uv.lock` **antes** do primeiro `fly deploy`.

**`.dockerignore`** (novo):

```
.venv
frontend/node_modules
frontend/*.tsbuildinfo
data
backups
uploads
tests
scripts
.git
.pytest_cache
__pycache__
*.xlsx
.env
```

`frontend/*.tsbuildinfo` não é firula: o `build` do frontend é `tsc -b && vite build`, e
os `tsconfig.*.tsbuildinfo` da sua máquina existem no repo local. Copiados para dentro
do contêiner, o `tsc -b` pode julgar o projeto "já compilado" e pular a emissão.

**`fly.toml`** (novo):

```toml
app = 'consultor'
primary_region = 'gru'

[build]
  dockerfile = 'Dockerfile'

[env]
  DATABASE_URL = 'sqlite:////data/carteira.db'   # 4 barras = caminho absoluto
  PRICE_PROVIDER = 'brapi'
  ANTHROPIC_MODEL = 'claude-sonnet-4-6'
  AGENT_MAX_ITERS = '6'
  QUOTE_CACHE_TTL_SECONDS = '900'
  ENV = 'production'

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = 'suspend'
  auto_start_machines = true
  min_machines_running = 0

  [http_service.concurrency]
    type = 'requests'
    soft_limit = 20
    hard_limit = 40

  [[http_service.checks]]
    path = '/health/live'
    interval = '30s'
    timeout = '5s'
    grace_period = '20s'

[[mounts]]
  source = 'consultor_data'
  destination = '/data'
  initial_size = '1gb'

[[vm]]
  size = 'shared-cpu-1x'
  memory = '512mb'
```

Sobre `DATABASE_URL = 'sqlite:////data/carteira.db'`: as quatro barras são deliberadas e
`app/database.py` lida bem com elas. Ele faz `url.removeprefix("sqlite:///")`, o que
sobra `/data/carteira.db` — caminho absoluto, dentro do volume. O `mkdir(parents=True,
exist_ok=True)` sobre `/data` é inofensivo, já que o ponto de montagem já existe.

Nota: `[deploy] release_command` **não** é usado — a máquina temporária dele não
enxerga o volume. A criação de tabelas e os seeds continuam no `lifespan`, que é
onde já estão e onde funcionam.

### Bloco B — Ajustes pequenos

1. **`app/api/health.py`**: o `/health` atual chama BCB **e Yahoo** a cada request.
   Como alvo de health check rodando a cada 30 s, isso é uma tempestade de requests
   externos — e derruba a máquina como "unhealthy" toda vez que o Yahoo tossir.
   Adicionar `GET /health/live`: só responde `{"status":"ok"}` + um `SELECT 1`.
   O `/health` completo continua existindo para diagnóstico manual.
2. **`app/api/health.py`, de novo**: `_check_yfinance()` é síncrono (`yf.Ticker(...)`,
   rede bloqueante) dentro de uma rota `async def`. Isso trava o event loop inteiro
   pelos segundos que a chamada demorar — hoje passa batido porque só existe você
   apertando F5, mas com um health check automático fica ruim. Envolver em
   `run_in_threadpool` (ou tornar a rota `def`). Mesmo tratamento vale para o provider
   síncrono usado dentro das rotas.
3. **`app/database.py`**: em SQLite, ligar `PRAGMA journal_mode=WAL` e
   `connect_args={"timeout": 30}` (hoje só há `check_same_thread: False`). O uvicorn
   atende requests em threads; sem WAL, uma escrita concorrente vira
   `database is locked`. Hoje passa despercebido porque você é um usuário só numa aba só.
4. **`app/main.py`**: `docs_url=None, redoc_url=None` quando `ENV=production`.
5. **`app/config.py`**: campos `env: str = "development"`, `app_password: str = ""` e
   `session_secret: str = ""`. O `extra="ignore"` já existente evita que qualquer
   variável a mais do Fly quebre o boot.
6. **`.env.example`**: acrescentar `PRICE_PROVIDER`, `ENV`, `APP_PASSWORD` e
   `SESSION_SECRET`, que hoje faltam — o arquivo é a documentação de fato da config.

`TAMANHO_MAXIMO` do upload (`app/api/extrato.py:19`, 5 MB) fica como está — o limite de
4,5 MB era da Vercel.

### Bloco C — Autenticação (obrigatório)

Sem isso a URL pública expõe patrimônio, CPF e conta — e sua chave Anthropic, que
qualquer um poderia queimar via `/chat`.

7. **`pyproject.toml` + `uv.lock`**: adicionar `itsdangerous>=2.2.0`. **Correção da
   rev. 1**, que afirmava que ele "já vem com o Starlette" — não vem: é extra opcional
   (`starlette[full]`), não está no `uv.lock` nem no `.venv` atual. Depois de editar o
   `pyproject.toml`, rodar `uv lock` e commitar o lock.
8. **`app/auth.py`** (novo): middleware exigindo cookie de sessão assinado
   (`SessionMiddleware` do Starlette, que é justamente o que precisa do `itsdangerous`).
   `POST /login` compara com `APP_PASSWORD` em tempo constante
   (`secrets.compare_digest`) e emite cookie HttpOnly + Secure + SameSite=Lax, 30 dias.
   Rotas livres, e a lista importa:
   - `/health/live` — senão o health check do Fly leva 401 e a máquina nunca fica saudável;
   - `/static/*` — o `base: '/static/'` do Vite faz o `index.html` referenciar os assets
     por lá;
   - `/` — precisa devolver o `index.html` mesmo deslogado, senão não há SPA para
     desenhar a tela de senha;
   - `/login`.

   Todo o resto (`/chat`, `/dashboard`, `/posicoes`, `/extrato`, `/snapshots`,
   `/rebalanceamento`) responde 401 sem cookie.
9. **`frontend/src/components/Login.tsx`** (novo): tela de senha, exibida quando
   qualquer chamada volta 401.

O streaming não atrapalha aqui: `frontend/src/lib/api.ts:156` consome
`POST /chat/stream` com `fetch` lendo o corpo (não `EventSource`, que não faz POST), e
`fetch` de mesma origem manda cookie por padrão. Não é preciso mexer no `credentials`.

### Bloco D — Opcional

10. **Imagem enxuta**: `yfinance` arrasta `pandas` + `numpy` — a imagem sai de ~350 MB
    para ~1,5 GB. Com `PRICE_PROVIDER=brapi`, dá para tornar o fallback yfinance um
    import opcional (`try/except ImportError`) em `app/providers/composite.py` e
    `app/api/health.py` e sair com o extra `--extra yfinance`. Economia real:
    ~US$ 0,20/mês de rootfs — irrisório. O ganho de verdade é deploy e cold start bem
    mais rápidos. (Cuidado: `app/tools/btg_xlsx_parser.py` usa `openpyxl`, não `pandas`
    — vale conferir se mais alguém importa `pandas` antes de cortar.)
11. **Backup automatizado**: `scripts/backup_remoto.ps1` puxando o `.db` semanalmente
    (passo manual 8).
12. **Snapshot mensal agendado**: `fly machine run` semanal chamando `POST /snapshots`,
    ou simplesmente continuar clicando na UI.

---

## 3. Ordem de execução

```
A (Docker + fly.toml) + B (ajustes)  →  deploy de teste, app privado
      → C (auth)  →  copiar o banco  →  validação  →  domínio (opcional)
```

Não exponha a URL antes do Bloco C.

---

## 4. Passo a passo manual (você faz)

### Passo 1 — Instalar o flyctl e criar a conta

No PowerShell:

```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

Feche e reabra o terminal (o instalador mexe no `PATH`), depois:

```powershell
fly version
fly auth signup     # ou: fly auth login, se já tiver conta
```

O Fly **exige cartão de crédito** mesmo com gasto baixo — não há free tier desde
outubro de 2024. Cadastre em Billing no dashboard.

### Passo 2 — Token da brapi

Crie conta em <https://brapi.dev> e guarde o token. Entra como secret no passo 5.

O plano gratuito costuma bastar para uma carteira pessoal. Vale testar se, rodando de
`gru`, o Tesouro volta a responder (gap G7) — se voltar, é o IP brasileiro resolvendo
o problema de graça.

### Passo 3 — Criar o app 🔗 (depois dos Blocos A e B)

Na raiz do projeto:

```powershell
fly launch --no-deploy --copy-config --name consultor --region gru
```

- `--copy-config` usa o `fly.toml` que eu já terei escrito, em vez de gerar um novo.
- Se `consultor` estiver tomado, use outro nome e ajuste o campo `app` no `fly.toml`.
- Ele pode perguntar sobre criar um Postgres/Redis: **responda não** para ambos.
- Se ele alterar o `fly.toml` no meio do caminho, confira com `git diff` antes de seguir.

### Passo 4 — Criar o volume

```powershell
fly volumes create consultor_data --region gru --size 1
```

Confirme com `fly volumes list`. É onde o `carteira.db` vai morar — 1 GB é 12.000×
o tamanho atual do banco (~80 KB), e é o mínimo cobrado de qualquer forma.

Este passo é tecnicamente opcional — o `initial_size` em `[[mounts]]` faria o Fly criar
o volume sozinho no primeiro deploy. Criar à mão é melhor: você escolhe a região
explicitamente e vê o volume existir antes de qualquer deploy tocar nele.

### Passo 5 — Secrets

```powershell
fly secrets set ANTHROPIC_API_KEY="sk-ant-..." BRAPI_TOKEN="seu-token" APP_PASSWORD="uma-senha-forte-nova" SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
```

Cada `fly secrets set` reinicia a máquina — por isso tudo num comando só.
`fly secrets list` mostra os nomes (nunca os valores).

O que **não** é secret já está em `[env]` no `fly.toml`: modelo, provider, TTL etc.

### Passo 6 — Primeiro deploy

```powershell
fly deploy --ha=false
```

O `--ha=false` importa no primeiro deploy: sem ele, o flyctl tende a criar duas máquinas
para um `http_service`. Duas máquinas com um volume só é exatamente o cenário que o
SQLite não suporta — a segunda subiria sem banco. Nos deploys seguintes o número de
máquinas já está fixado e a flag é dispensável.

O build roda num builder remoto do Fly (não usa Docker local). Leva ~3–5 min na
primeira vez — depois as camadas ficam em cache. Acompanhe com `fly logs`.

Ao final: `fly status` deve mostrar **1** máquina `started` em `gru`, e
`fly open /health` deve responder JSON. Se aparecerem duas, derrube a extra com
`fly machine destroy <ID>`.

### Passo 7 — Copiar o seu banco para o volume 🔗

O app já terá criado um `carteira.db` vazio com os seeds. Substitua pelo seu:

```powershell
# 1. Checkpoint do WAL + integrity_check + backup em backups\
#    (obrigatório: o banco local roda em WAL desde o Bloco B)
uv run python scripts/preparar_db_para_upload.py

# 2. Enviar para um nome temporário (a máquina PRECISA estar rodando)
fly machine list
fly ssh sftp shell
# no prompt do sftp:
#   put data/carteira.db /data/carteira.novo.db
#   quit

# 3. Trocar no lugar, levando junto o -wal e o -shm do banco vazio
fly ssh console -C "sh -c 'rm -f /data/carteira.db /data/carteira.db-wal /data/carteira.db-shm && mv /data/carteira.novo.db /data/carteira.db'"

# 4. Reiniciar para o app abrir o arquivo novo
fly machine restart <ID-DA-MAQUINA>
```

Duas correções em relação ao que a rev. 2 mandava fazer aqui, e as duas doem se
ignoradas:

- **Não pare a máquina antes.** `fly ssh` (sftp inclusive) fala com uma máquina *rodando* —
  com ela parada, o upload simplesmente não acontece. O que protege a cópia não é a máquina
  estar parada, é você fazer isto **antes de começar a usar o app publicado**.
- **Apague o `-wal` e o `-shm` junto.** O primeiro deploy já subiu um banco vazio em WAL.
  Trocar só o `.db` deixaria para trás o WAL do banco antigo ao lado do arquivo novo — na
  melhor das hipóteses ele é ignorado, na pior você abre um banco inconsistente. Remover os
  três e mover o novo por cima elimina a dúvida. Apagar o `.db` com o processo segurando o
  arquivo é seguro no Linux (o inode vive até o restart do passo 4).

O passo 1 não é burocracia: com o WAL ligado, as últimas escritas ficam em
`carteira.db-wal` até o checkpoint. Copiar só o `.db` perderia esses dados **sem avisar**.
O script faz o `PRAGMA wal_checkpoint(TRUNCATE)`, confere a integridade e funciona
igualmente se o banco ainda estiver em journal clássico. Ele avisa se o uvicorn estiver
de pé segurando o banco — feche antes de rodar.

Confira o resultado antes de seguir:

```powershell
fly ssh console -C "ls -la /data"
```

### Passo 8 — Backup recorrente

Snapshots automáticos do volume existem (diários, retenção de 5 dias), mas a própria
documentação avisa que **podem não conter os dados mais recentes**. Não confie neles
como único backup.

```powershell
# Checkpoint antes de baixar — no servidor o banco também roda em WAL, e um
# `get` cru do .db deixaria as últimas escritas para trás.
fly ssh console -C "python -c \"import sqlite3; c=sqlite3.connect('/data/carteira.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()\""
fly ssh sftp get /data/carteira.db "backups\carteira-$(Get-Date -f yyyyMMdd).db"
```

Rode semanalmente — ou agende com o Task Scheduler do Windows. Configure também a
retenção dos snapshots para 30 dias no dashboard (Volumes → Snapshots).

### Passo 9 — Validação em produção

Com `https://consultor.fly.dev`:

1. `/health/live` responde `{"status":"ok"}` sem senha. O `/health` completo (com `bcb` e
   Tesouro) é rota protegida — abra depois de logar, na mesma janela.
2. Login com a `APP_PASSWORD`; janela anônima deve pedir senha. Confirme também que
   `GET /dashboard` sem cookie devolve 401 (`curl -i https://consultor.fly.dev/dashboard`)
   — é o teste que realmente prova o Bloco C.
3. Dashboard mostra suas posições reais, com os valores que você reconhece.
4. Chat: "como está minha carteira?" — o texto deve vir **streamado**, token a token,
   com as tools aparecendo. (SSE atravessa o Fly Proxy sem configuração extra.)
5. Segunda mensagem dependente da primeira → confirma o histórico.
6. Upload de um XLSX real → preview → "sim" → posições gravadas.
7. **Teste da suspensão:** espere ~10 min sem tocar, confirme com `fly status` que a
   máquina está `suspended`, e então mande uma mensagem na conversa anterior. Deve
   responder em menos de 1 s **e lembrar do contexto** — é o snapshot de RAM voltando.
   Se a máquina aparecer como `stopped` em vez de `suspended`, o Fly caiu para o modo
   normal (acontece, por exemplo, em manutenção de host): tudo continua funcionando,
   só o histórico do chat em RAM se perde.
8. Reinicie de propósito (`fly machine restart <ID>`) e confirme que o banco continua
   lá — é o que separa "o volume está montado" de "estou gravando no rootfs efêmero".

### Passo 10 — Domínio próprio (opcional)

```powershell
fly certs add consultor.seudominio.com.br
fly certs show consultor.seudominio.com.br    # mostra os registros DNS a criar
```

Aponte o CNAME/A no seu provedor de DNS. O certificado é emitido automaticamente.
Continue usando o IPv4 **compartilhado** (gratuito) — um dedicado custa US$ 2/mês e
você não precisa dele.

---

## 5. Custo real

| Item | Preço | Estimativa aqui |
|---|---|---|
| Máquina `shared-cpu-1x` 512 MB rodando | US$ 0,0046/h | US$ 3,32 se 24/7; com autosuspend, **~US$ 0,50–1,50** |
| Máquina suspensa (rootfs) | US$ 0,15/GB/mês | ~US$ 0,20 (imagem ~1,5 GB) ou ~US$ 0,05 com a imagem enxuta |
| Volume 1 GB | US$ 0,15/GB/mês | US$ 0,15 |
| Snapshots | US$ 0,08/GB/mês | US$ 0 (10 GB grátis/mês) |
| Egress de `gru` | US$ 0,04/GB | ~US$ 0 |
| IPv4 compartilhado + IPv6 + TLS | grátis | US$ 0 |
| **Infra, total** | | **~US$ 1–2/mês** |
| Anthropic | pay-per-use | ~US$ 0,01–0,05 por turno |

Como sempre, o gasto real é a API da Anthropic — o que torna o Bloco C inegociável.

---

## 6. Riscos conhecidos

| Risco | Mitigação |
|---|---|
| **Uma máquina + um volume = ponto único de falha.** O Fly recomenda dois volumes por app; com SQLite isso não é possível | Backup semanal do `.db` (passo 8) + snapshots com retenção de 30 dias. Para um app pessoal, restaurar em minutos é aceitável |
| Deploy tem alguns segundos de downtime (a máquina com volume é parada antes de subir a nova) | Irrelevante para um usuário |
| Um segundo Machine criado por engano (deploy sem `--ha=false`, `fly scale count 2`) subiria sem volume e com banco vazio | `fly status` depois de cada deploy; o número de máquinas deve ser sempre 1 |
| Conexões abertas quebram na retomada de um suspend (`ECONNRESET`) | Só afeta conexões de longa duração; requests HTTP normais são imunes. Um SSE em andamento não sofre — a máquina não suspende enquanto há tráfego |
| Deploy/restart zera `_sessions` e `extrato_staging` (RAM só sobrevive ao *suspend*) | Comportamento idêntico ao de reiniciar o uvicorn hoje; o código já orienta a resubir o extrato |
| Cartão de crédito obrigatório, sem free tier | Defina um alerta de gasto no dashboard do Fly |
| brapi no plano gratuito pode limitar | yfinance segue como fallback; o cache de 15 min já reduz muito o volume de chamadas |
| Máquina de 512 MB com `pandas` carregado | Se der OOM, `fly scale memory 1024` (~US$ 6,60/mês 24/7); ou o Bloco D, que remove o `pandas` |

---

## 7. O que foi verificado no código (rev. 2)

Conferido contra o repositório em 11/08/2026, para que ninguém tenha que refazer:

| Afirmação do plano | Situação |
|---|---|
| `itsdangerous` vem com o Starlette | ❌ **Falso.** Não está no `uv.lock` nem no `.venv` (só `starlette 1.2.1`). Vira dependência nova + `uv lock` |
| `Dockerfile` precisa de `COPY static/` no estágio de build | ❌ **Falso e prejudicial** — `emptyOutDir: true` apaga a pasta; todo o `static/` é saída do Vite |
| `uv.lock` está em dia com o `pyproject.toml` | ✅ Sim, hoje. Deixa de estar assim que o Bloco C entrar |
| `docs/` é lido em runtime | ✅ `app/seeds.py:19` e `app/agent/system_prompt.py:20`, ambos resolvendo para `/app/docs` no contêiner |
| `sqlite:////data/…` funciona sem mexer no código | ✅ `app/database.py` usa `removeprefix("sqlite:///")` → `/data/carteira.db` |
| Build do Vite sai em `static/` | ✅ `frontend/vite.config.ts`: `outDir: '../static'`, `base: '/static/'` |
| `/health` chama BCB + Yahoo a cada request | ✅ `app/api/health.py`; e o check do yfinance é síncrono dentro de rota `async` |
| `app/database.py` não tem WAL nem timeout | ✅ Só `check_same_thread: False` |
| `app/config.py` não tem `env`/`app_password`/`session_secret` | ✅ Confirmado — os três são novos |
| Estado de chat e staging em memória de processo | ✅ `app/api/chat.py:22` (`_sessions`) e `app/tools/extrato_staging.py` (singleton com lock) |
| Streaming sobrevive ao cookie de sessão | ✅ `frontend/src/lib/api.ts:156` usa `fetch` POST, que envia cookie de mesma origem por padrão |
| Limite de upload de 5 MB | ✅ `app/api/extrato.py:19` |
| Rotas a liberar na auth | ✅ Routers registrados em `app/main.py`: health, chat, posicoes, snapshots, dashboard, rebalanceamento, extrato |

---

## 8. Estado da execução (rev. 3 — 13/08/2026)

Blocos A, B e C implementados. Bloco D (imagem enxuta, backup e snapshot agendados)
continua em aberto, como previsto.

| Bloco | Arquivos |
|---|---|
| A — empacotamento | `Dockerfile`, `.dockerignore`, `fly.toml` (os três novos, como escritos em §2) |
| B — ajustes | `app/api/health.py`, `app/database.py`, `app/main.py`, `app/config.py`, `.env.example` |
| C — autenticação | `app/auth.py` (novo), `frontend/src/components/Login.tsx` (novo), `frontend/src/lib/api.ts`, `frontend/src/App.tsx`, `pyproject.toml` + `uv.lock` |
| Apoio | `scripts/preparar_db_para_upload.py`, `tests/test_auth.py` |

### Onde o código ficou diferente do plano

1. **WAL vale também no local, não só no servidor.** O plano dizia "o Bloco B liga o WAL
   só no servidor"; `app/database.py` liga para qualquer SQLite, porque o problema
   (uvicorn atendendo em threads) é o mesmo nas duas pontas. Consequência prática: o
   **passo 7 passa a exigir** `uv run python scripts/preparar_db_para_upload.py` antes de
   enviar o `.db` — o script faz `wal_checkpoint(TRUNCATE)`, roda `integrity_check`,
   guarda uma cópia em `backups/` e imprime os comandos do `sftp`.
2. **`/health` completo é rota protegida; só `/health/live` é livre.** Segue a lista do
   Bloco C à risca. Efeito colateral no **passo 9.1**: `fly open /health` só responde
   depois do login na mesma janela — para checar sem sessão, use `/health/live`.
3. **Três rotas livres a mais do que a lista original**: `/logout`, `/auth/status` e
   `/favicon.ico`. O `/auth/status` é o que permite ao frontend saber, no boot, se deve
   desenhar a tela de senha ou a aplicação.
4. **`ENV=production` sem `APP_PASSWORD`/`SESSION_SECRET` não sobe** — `configurar_auth()`
   levanta `RuntimeError` no boot. É deliberado: uma URL pública aberta é pior que um
   deploy que falha na cara.
5. **`AuthGuardMiddleware` é ASGI puro**, não `BaseHTTPMiddleware`. O chat responde em SSE
   e envolver o corpo em mais uma camada de streaming só traria risco de buffering.
6. **`openapi_url` também é desligado em produção**, além de `docs_url` e `redoc_url`.

### Validação local já feita

- `uv run pytest -q` → 43 testes passando antes do Bloco C; `tests/test_auth.py`
  acrescenta 8 (401 sem cookie, `/health/live` livre, senha errada, login, logout,
  `/auth/status`, app aberto sem senha, boot barrado em produção sem senha).
- `npm run build --prefix frontend` → build limpo, `static/` regenerado.
- Smoke do app real com `ENV=production`: `/health/live` 200, `/dashboard` 401 sem cookie
  e 200 depois do login, `/docs` e `/openapi.json` inacessíveis, cookie com
  `Secure`+`HttpOnly`+`SameSite=Lax`, `journal_mode=wal`.

### A imagem foi construída e rodada localmente (13/08/2026)

`docker build -t consultor:local .` passa. O contêiner foi levantado como roda no Fly
(`ENV=production`, volume em `/data`, `DATABASE_URL=sqlite:////data/carteira.db`):

- boot limpo, seeds lendo `docs/perfil_risco_investidor.md` de dentro da imagem — o
  `COPY docs/` está certo;
- `/health/live` 200 · `/dashboard` 401 · `/` 200 · `/docs` 401 · asset do Vite
  (`/static/assets/index-*.css`) 200 · login com senha errada 401, correta 200;
- **imagem de 908 MB** (o `pandas`/`numpy` do yfinance é a maior fatia). Fica abaixo dos
  ~1,5 GB estimados em §5: o rootfs suspenso custa ~US$ 0,14/mês, não US$ 0,20.
- `ls /data` depois do boot mostra `carteira.db`, `carteira.db-shm` e **`carteira.db-wal`**
  — a confirmação prática de por que o passo 7 apaga os três antes de mover o banco novo.

O que só pode ser feito com a sua conta: `fly auth login` (navegador + cartão) e tudo o que
vem depois — §4, passos 1 a 10. O `flyctl` v0.4.83 já está instalado em
`%USERPROFILE%\.fly\bin\flyctl.exe`.
