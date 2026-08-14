import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .database import create_tables
from .auth import configurar_auth, router as auth_router
from .api.health import router as health_router
from .api.chat import router as chat_router
from .api.posicoes import router as posicoes_router
from .api.snapshots import router as snapshots_router
from .api.dashboard import router as dashboard_router
from .api.rebalanceamento import router as rebalanceamento_router
from .api.extrato import router as extrato_router
from .seeds import seed_all

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Consultor iniciando — criando tabelas e semeando dados iniciais...")
    create_tables()
    seed_all()
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY nao configurada — copie .env.example para .env e preencha a chave."
        )
    else:
        logger.info("Modelo: %s | provider: %s", settings.anthropic_model, settings.price_provider)
    logger.info("Consultor pronto em http://127.0.0.1:8000")
    yield
    logger.info("Consultor encerrado.")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_settings = get_settings()

app = FastAPI(
    title="Consultor Financeiro Pessoal",
    description="Agente consultivo local — single-user.",
    version="0.1.0",
    lifespan=lifespan,
    # Em produção a documentação interativa não tem por que ficar exposta.
    docs_url=None if _settings.is_production else "/docs",
    redoc_url=None if _settings.is_production else "/redoc",
    openapi_url=None if _settings.is_production else "/openapi.json",
)

configurar_auth(app)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(posicoes_router)
app.include_router(snapshots_router)
app.include_router(dashboard_router)
app.include_router(rebalanceamento_router)
app.include_router(extrato_router)

# Serve arquivos estáticos (UI) de /static
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"status": "ok", "app": "Consultor Financeiro Pessoal", "version": "0.1.0"}
