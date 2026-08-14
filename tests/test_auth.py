"""
Autenticação de sessão (docs/PLANO_DEPLOY_FLY.md, Bloco C).

O que estes testes protegem: a URL pública não pode entregar carteira nem /chat
sem cookie — é o que separa "publicado" de "vazado". E o inverso também importa:
sem APP_PASSWORD o app tem de continuar aberto, como sempre foi localmente.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import configurar_auth, router as auth_router
from app.config import Settings

SENHA = "senha-de-teste-123"


@pytest.fixture
def client(monkeypatch):
    """App mínimo com a auth instalada e uma rota protegida de mentira."""
    settings = Settings(
        _env_file=None, app_password=SENHA, session_secret="x" * 48, env="development"
    )
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/dashboard")
    async def _dashboard():
        return {"total": 42}

    @app.get("/health/live")
    async def _live():
        return {"status": "ok"}

    configurar_auth(app)
    return TestClient(app)


def test_rota_protegida_sem_cookie_devolve_401(client):
    assert client.get("/dashboard").status_code == 401


def test_health_live_responde_sem_cookie(client):
    # Se levasse 401, o health check do Fly nunca daria a máquina como saudável.
    assert client.get("/health/live").status_code == 200


def test_login_com_senha_errada_nao_libera(client):
    resp = client.post("/login", json={"senha": "chute"})
    assert resp.status_code == 401
    assert client.get("/dashboard").status_code == 401


def test_login_correto_libera_as_rotas(client):
    assert client.post("/login", json={"senha": SENHA}).status_code == 200
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.json() == {"total": 42}


def test_logout_revoga_o_acesso(client):
    client.post("/login", json={"senha": SENHA})
    assert client.get("/dashboard").status_code == 200

    client.post("/logout")
    assert client.get("/dashboard").status_code == 401


def test_auth_status_reflete_a_sessao(client):
    antes = client.get("/auth/status").json()
    assert antes == {"auth_required": True, "authenticated": False}

    client.post("/login", json={"senha": SENHA})
    assert client.get("/auth/status").json()["authenticated"] is True


def test_sem_senha_configurada_o_app_fica_aberto(monkeypatch):
    settings = Settings(_env_file=None, app_password="", env="development")
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/dashboard")
    async def _dashboard():
        return {"total": 42}

    configurar_auth(app)
    cliente = TestClient(app)

    assert cliente.get("/dashboard").status_code == 200
    assert cliente.get("/auth/status").json() == {
        "auth_required": False,
        "authenticated": True,
    }


def test_producao_sem_senha_nao_sobe(monkeypatch):
    """Erro no boot é melhor que uma URL pública aberta."""
    settings = Settings(_env_file=None, env="production", app_password="", session_secret="")
    monkeypatch.setattr("app.auth.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="APP_PASSWORD"):
        configurar_auth(FastAPI())
