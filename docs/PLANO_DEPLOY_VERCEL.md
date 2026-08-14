# Plano de deploy na Vercel — Consultor Financeiro Pessoal

Rev. 1 — 10/08/2026

---

## 0. Leia isto antes

O projeto foi construído com três premissas que a Vercel **não** oferece: processo
único e permanente, disco gravável e ausência de rede pública. Concretamente:

| Premissa atual | O que acontece na Vercel |
|---|---|
| SQLite em `data/carteira.db` | Filesystem read-only (só `/tmp`, efêmero e por instância) — o banco **some** a cada invocação |
| Histórico do chat em `_sessions` (dict de módulo) | Cada instância tem o seu; o agente esquece a conversa de forma aleatória |
| Preview do extrato em `extrato_staging` (singleton) | O upload cai numa instância e o `importar_extrato()` do turno seguinte pode cair em outra |
| Sem autenticação (`127.0.0.1` é a proteção) | URL pública com CPF, conta e patrimônio expostos a quem tiver o link |
| `yfinance` / Tesouro a partir da sua casa | IP de datacenter (AWS `iad1`) é bloqueado/429 com muito mais frequência |

Nada disso impede o deploy — mas **os quatro primeiros itens exigem mudança de
código antes de subir**, não são ajuste de configuração.

**Alternativa honesta:** um host de contêiner com disco persistente (Render, Fly.io,
Railway) roda este código praticamente como está — só faltaria autenticação. A Vercel
custa ~2 dias de refatoração (banco + estado + auth). Se a escolha da Vercel for por
CDN/domínio/preço, o plano abaixo entrega; se for só "onde hospedar", vale reconsiderar.
Seguindo com Vercel a partir daqui.

---

## 1. Arquitetura alvo

Um único projeto Vercel, um único deployment:

```
GitHub repo
  └── Vercel Project "consultor"
        ├── Build:  npm run build (frontend/) → static/   → promovido para a CDN
        ├── Função: app/main.py (FastAPI ASGI, Python 3.12, fluid compute)
        └── Neon Postgres (Marketplace)  ← DATABASE_URL
```

Por que assim:

- A Vercel detecta automaticamente o `app` FastAPI em `app/main.py` (é um dos
  entrypoints suportados: `main.py` dentro de `app/`). **Zero mudança de entrypoint.**
- `app.mount("/static", StaticFiles(...))` faz a Vercel promover os assets para a CDN
  no build — o JS/CSS não passa pela função.
- Frontend e API na mesma origem → o `fetch('/chat')` relativo do `lib/api.ts`
  continua funcionando, sem CORS.
- Streaming (SSE do `/chat/stream`) é suportado no runtime Python.

Limites relevantes (plano Hobby, fluid compute):

| Limite | Valor | Impacto aqui |
|---|---|---|
| Duração máxima | 300 s | Folgado — turno do agente com 6 iterações fica bem abaixo |
| Bundle Python | 500 MB | Folgado — `anthropic` + `yfinance`/`pandas` + `openpyxl` ≈ 120 MB |
| Body de request/response | **4,5 MB** | O upload do extrato hoje aceita 5 MB → precisa baixar o teto |
| Memória | 2 GB | Folgado |
| Região | `iad1` (padrão) | Trocar para `gru1` ajuda com brapi/Tesouro |

---

## 2. Mudanças de código (eu faço)

### Bloco A — Banco: SQLite → Postgres (Neon)

Nenhum SQL específico de SQLite foi usado no projeto (conferido: só `SELECT 1` no
health e queries do SQLModel), então a troca é de driver e engine.

1. `pyproject.toml`: adicionar `psycopg[binary]>=3.2`; remover `pandas` da lista
   explícita (não é importado em `app/` — vem junto do `yfinance` de qualquer forma).
2. `app/database.py`:
   - normalizar a URL que a Neon injeta (`postgres://…`) para
     `postgresql+psycopg://…`;
   - em Postgres, criar o engine com `poolclass=NullPool` e `pool_pre_ping=True`
     (serverless não deve segurar pool; a Neon já tem pooler à frente);
   - manter o caminho SQLite intacto para o desenvolvimento local.
3. `app/main.py`: tirar `create_tables()` e `seed_all()` do `lifespan`. Em serverless
   isso roda a cada cold start e pode ter duas instâncias semeando ao mesmo tempo.
   Passa a ser um script explícito (Bloco E), com o lifespan apenas logando.
4. `scripts/bootstrap_db.py` (novo): cria tabelas + roda `seed_all()` contra a
   `DATABASE_URL` do ambiente. Idempotente.
5. `scripts/migrar_sqlite_para_postgres.py` (novo): lê o `data/carteira.db` atual pelos
   próprios modelos SQLModel e reinsere no Postgres. São 81 KB de dados; leva segundos.

### Bloco B — Estado em memória → banco

6. `app/models/sessao_chat.py` (novo): tabela `SessaoChat(session_id PK, history_json,
   atualizado_em)`. `app/api/chat.py` passa a ler/gravar o histórico ali em vez do dict
   `_sessions`. O contrato da API não muda — o frontend continua mandando só
   `message` + `session_id`.
7. `app/models/extrato_staging.py` (novo): tabela `ExtratoStaging(session_id PK,
   preview_json, arquivo, recebido_em)`. `app/tools/extrato_staging.py` troca o
   singleton de processo por essa tabela, mantendo a mesma interface
   (`set_preview` / `get` / `clear`), com expiração de ~2 h.
   - Consequência de contrato: `POST /extrato/upload` e `GET/DELETE /extrato/preview`
     passam a receber `session_id`, e `ModalImport.tsx` / `lib/api.ts` passam a enviá-lo.
     Sem isso, dois navegadores compartilhariam o mesmo staging.
   - O guardrail continua valendo: o preview é estruturado (sem o binário com
     CPF/conta) e a gravação segue exclusiva do `gravar_posicoes`.
8. `app/api/extrato.py`: `TAMANHO_MAXIMO` de 5 MB → 4 MB (teto de 4,5 MB da Vercel).
   O extrato real tem ~25 KB.

### Bloco C — Autenticação (obrigatório)

Sem isso, a URL pública expõe patrimônio, CPF e a sua chave Anthropic (qualquer um
consegue queimar créditos pelo `/chat`).

9. `app/auth.py` (novo): middleware que exige um cookie de sessão assinado; libera
   apenas `/health`, `/login` e `/static/*`. `POST /login` compara a senha com
   `APP_PASSWORD` (env var, comparação em tempo constante) e emite o cookie
   HttpOnly + Secure + SameSite=Lax, com validade de 30 dias.
10. `frontend/src/components/Login.tsx` (novo): tela simples de senha, exibida quando
    qualquer chamada volta 401.
11. `/docs` e `/openapi.json` desabilitados em produção (`FastAPI(docs_url=None)`
    quando `ENV=production`).

### Bloco D — Provedores de preço em produção

12. `PRICE_PROVIDER=brapi` + `BRAPI_TOKEN` em produção. Yahoo (yfinance) bloqueia IP de
    datacenter com frequência — ele continua como fallback, mas não pode ser o primário.
13. O 403 do Tesouro (gap G7, já conhecido) tende a piorar em `iad1`; a região `gru1`
    (São Paulo) é a mitigação, definida no passo manual 6.

### Bloco E — Configuração de deploy

14. `vercel.json` (novo):
    ```json
    {
      "$schema": "https://openapi.vercel.sh/vercel.json",
      "buildCommand": "npm ci --prefix frontend && npm run build --prefix frontend",
      "functions": { "app/main.py": { "maxDuration": 300 } }
    }
    ```
15. `.python-version` (novo): `3.12`.
16. `.vercelignore` (novo): exclui `tests/`, `scripts/`, `backups/`, `data/`,
    `.venv/`, `frontend/node_modules/`.
    **Atenção:** `docs/` precisa ficar no bundle — `system_prompt.py` e `seeds.py` leem
    `docs/system_prompt_consultor_otimizado.md` e `docs/perfil_risco_investidor.md`
    em runtime.
17. `README.md`: seção de deploy e de execução local com Postgres.

### Bloco F — Opcional, depois do primeiro deploy verde

18. Vercel Cron chamando `POST /snapshots` no dia 1 de cada mês (hoje é manual).
    Exige um bypass de auth por token no header para o cron.
19. Backup: `pg_dump` agendado, ou os snapshots mensais como backup lógico.

---

## 3. Ordem de execução

```
A (banco) → E (config) → deploy de teste  ← primeiro deployment verde, ainda sem auth,
                                             com Deployment Protection ligada
B (estado) → C (auth) → D (providers) → deploy final → domínio
```

Não vale subir sem o Bloco C, nem com a Deployment Protection desligada antes dele.

---

## 4. Passo a passo manual (você faz)

Os passos marcados 🔗 dependem de mim ter terminado o bloco de código indicado.

### Passo 1 — Conta e repositório

1. Crie conta em <https://vercel.com> (login com GitHub é o mais direto).
2. Confirme que o repo está no GitHub e que `main` está atualizada. Hoje há bastante
   coisa não commitada (`git status` mostra ~30 arquivos modificados/novos) — precisa
   estar tudo commitado e pushado antes.
3. Confira que `data/`, `.env`, `backups/` e `*.xlsx` continuam no `.gitignore`
   (estão) — **nenhum extrato ou banco pode ir para o GitHub**.

### Passo 2 — Banco Postgres (Neon)

1. No dashboard da Vercel: **Storage** → **Create Database** → **Neon** (Postgres).
2. Plano **Free**. Região: escolha **AWS us-east-1** (mesma da função por padrão) —
   ou `sa-east-1` se você optar pela região `gru1` no passo 6; banco e função devem
   ficar na mesma região.
3. Nome sugerido: `consultor-db`.
4. Ao final, conecte o banco ao projeto Vercel (a Neon injeta `DATABASE_URL` e
   `POSTGRES_URL` automaticamente nas env vars do projeto).
5. Copie a **connection string com pooler** (a que tem `-pooler` no host) — você vai
   usá-la localmente no passo 4.

### Passo 3 — Token da brapi

1. Crie conta em <https://brapi.dev> e pegue o token.
2. Guarde — entra como env var no passo 5.
   (O plano gratuito da brapi costuma bastar para uma carteira pessoal; se o limite
   apertar, o yfinance segue como fallback.)

### Passo 4 — Migrar seus dados 🔗 (depois do Bloco A)

No PowerShell, na raiz do projeto:

```powershell
# 1. Backup do SQLite atual
Copy-Item data\carteira.db "backups\carteira-pre-postgres-$(Get-Date -f yyyyMMdd).db"

# 2. Apontar para a Neon (cole a string COM -pooler)
$env:DATABASE_URL = "postgresql://usuario:senha@ep-xxx-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require"

# 3. Criar tabelas + seeds
.venv\Scripts\python.exe -m scripts.bootstrap_db

# 4. Copiar posições, alvos, perfil, estratégia e snapshots do SQLite
.venv\Scripts\python.exe -m scripts.migrar_sqlite_para_postgres

# 5. Conferir
.venv\Scripts\python.exe -m scripts.verificar_migracao
```

O passo 5 imprime a contagem de linhas por tabela nos dois bancos — devem bater.

### Passo 5 — Criar o projeto na Vercel 🔗 (depois do Bloco E)

1. Dashboard → **Add New** → **Project** → importe o repositório do GitHub.
2. Framework Preset: a Vercel deve detectar **FastAPI**. Se aparecer "Other", deixe
   assim — o `vercel.json` já define o build.
3. **Não** clique em Deploy ainda. Abra **Environment Variables** e adicione (marcando
   Production, Preview e Development em todas):

   | Nome | Valor | Observação |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | `sk-ant-…` | do seu `.env` local |
   | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | |
   | `BRAPI_TOKEN` | token do passo 3 | |
   | `PRICE_PROVIDER` | `brapi` | |
   | `APP_PASSWORD` | senha forte, nova | a que você usará para entrar |
   | `SESSION_SECRET` | 32+ chars aleatórios | gere: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
   | `ENV` | `production` | desliga `/docs` |
   | `AGENT_MAX_ITERS` | `6` | |
   | `QUOTE_CACHE_TTL_SECONDS` | `900` | |

   `DATABASE_URL` já deve estar lá, vinda da Neon — **não duplique**.
4. Clique em **Deploy** e acompanhe o log de build.

### Passo 6 — Região (opcional, recomendado)

Settings → **Functions** → Function Region → **São Paulo (`gru1`)**.
Reduz latência com brapi/Tesouro/B3 e a chance do 403 do Tesouro. Só faz sentido se o
banco Neon também estiver em `sa-east-1` — senão cada query cruza o continente.

### Passo 7 — Proteção de acesso

Enquanto o Bloco C (auth no app) não estiver no ar, ligue a proteção da plataforma:
Settings → **Deployment Protection** → **Vercel Authentication: All Deployments**.
Assim só quem estiver logado na sua conta Vercel abre a URL.

Depois que a auth do app subir, pode manter as duas camadas ou desligar esta —
mas **nunca fique sem nenhuma das duas**.

### Passo 8 — Validação em produção

Com a URL do deploy (`https://consultor-xxx.vercel.app`):

1. `GET /health` → deve responder `ok`, com o check de banco verde.
2. Faça login com a `APP_PASSWORD`.
3. Dashboard carrega as posições migradas, com os valores que você conhece.
4. Chat: mande "como está minha carteira?" e confirme que o texto vem **streamado**
   (token a token) e que as tools aparecem rodando.
5. Segunda mensagem na mesma conversa: pergunte algo que dependa da primeira — valida
   que o histórico está persistindo (Bloco B).
6. Upload de um extrato XLSX real → preview aparece → responda "sim" → confirme que as
   posições foram gravadas. Valida o staging em banco.
7. Abra a URL numa janela anônima: deve pedir senha.

### Passo 9 — Domínio (opcional)

Settings → **Domains** → adicione o seu domínio e siga as instruções de DNS.

### Passo 10 — Custo, no fim das contas

| Item | Custo |
|---|---|
| Vercel Hobby | US$ 0 (uso pessoal; uso comercial exige Pro) |
| Neon Free | US$ 0 (0,5 GB — este banco tem 81 KB) |
| brapi | US$ 0 no plano free |
| Anthropic | pay-per-use, ~US$ 0,01–0,05 por turno (já logado pelo app) |

O gasto real é a API da Anthropic — daí a `APP_PASSWORD` ser obrigatória.

---

## 5. Riscos conhecidos

| Risco | Mitigação |
|---|---|
| Cold start de ~2–4 s (import de `anthropic` + `yfinance`) | Aceitável para uso pessoal; se incomodar, importar `yfinance` sob demanda |
| Yahoo/Tesouro bloqueando IP de datacenter | brapi como primário; região `gru1`; cache de cotações de 15 min |
| Neon Free suspende o banco após inatividade | Primeira query do dia leva ~1 s a mais; `pool_pre_ping` já cobre a reconexão |
| Extrato com CPF trafegando pela internet | HTTPS + auth + o binário nunca é persistido (só o preview estruturado) |
| Duas abas na mesma sessão de chat | `session_id` já separa; o staging passa a ser por sessão no Bloco B |
