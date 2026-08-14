"""
Autenticação de sessão — Bloco C do PLANO_DEPLOY_FLY.

Single-user: uma senha (APP_PASSWORD) e um cookie de sessão assinado. Sem senha
configurada o app roda aberto, que é o comportamento local de sempre; em
produção as duas variáveis são obrigatórias e o boot falha sem elas — a URL
pública expõe patrimônio, CPF, conta e a chave da Anthropic via /chat.
"""
import logging
import secrets

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

NOME_COOKIE = "consultor_session"
DURACAO_SESSAO = 30 * 24 * 60 * 60  # 30 dias

# Rotas que respondem sem cookie. A lista é curta e cada item tem motivo:
#   /health/live — senão o health check do Fly leva 401 e a máquina nunca sobe;
#   /static      — o base '/static/' do Vite referencia os assets por lá;
#   /            — o index.html precisa carregar deslogado, senão não há SPA
#                  para desenhar a tela de senha;
#   /login, /logout, /auth/status — a própria autenticação.
PREFIXOS_LIVRES = (
    "/health/live",
    "/static",
    "/login",
    "/logout",
    "/auth/status",
    "/favicon.ico",
)


def _rota_livre(path: str) -> bool:
    return path == "/" or path.startswith(PREFIXOS_LIVRES)


class AuthGuardMiddleware:
    """
    Middleware ASGI puro (não BaseHTTPMiddleware) — o chat responde em SSE e
    envolver o corpo em outra camada de streaming só traz risco de buffering.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or _rota_livre(scope["path"]):
            return await self.app(scope, receive, send)

        if not get_settings().auth_enabled:
            return await self.app(scope, receive, send)

        if scope.get("session", {}).get("auth") is True:
            return await self.app(scope, receive, send)

        resposta = JSONResponse({"detail": "Não autenticado."}, status_code=401)
        await resposta(scope, receive, send)


def configurar_auth(app: FastAPI) -> None:
    """Instala o guard e o SessionMiddleware. Chamado uma vez em main.py."""
    settings = get_settings()

    if settings.is_production and not (settings.app_password and settings.session_secret):
        raise RuntimeError(
            "ENV=production exige APP_PASSWORD e SESSION_SECRET. "
            "No Fly: fly secrets set APP_PASSWORD=... SESSION_SECRET=..."
        )

    # Sem secret configurado (uso local), um por processo já basta: com a
    # autenticação desligada o cookie não decide nada.
    secret = settings.session_secret or secrets.token_urlsafe(48)

    # add_middleware empilha de dentro para fora: o guard entra primeiro para
    # que o SessionMiddleware rode antes dele e popule scope["session"].
    app.add_middleware(AuthGuardMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie=NOME_COOKIE,
        max_age=DURACAO_SESSAO,
        same_site="lax",
        https_only=settings.is_production,
    )

    if settings.auth_enabled:
        logger.info("Autenticação por senha ativa (cookie %s, 30 dias).", NOME_COOKIE)
    else:
        logger.warning("APP_PASSWORD vazia — app aberto, sem autenticação.")


class PedidoLogin(BaseModel):
    senha: str


@router.get("/auth/status")
async def auth_status(request: Request):
    settings = get_settings()
    if not settings.auth_enabled:
        return {"auth_required": False, "authenticated": True}
    return {
        "auth_required": True,
        "authenticated": request.session.get("auth") is True,
    }


@router.post("/login")
async def login(request: Request, dados: PedidoLogin):
    settings = get_settings()
    if not settings.auth_enabled:
        return {"ok": True, "auth_required": False}

    if not secrets.compare_digest(dados.senha, settings.app_password):
        logger.warning("Tentativa de login com senha incorreta.")
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    request.session["auth"] = True
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
