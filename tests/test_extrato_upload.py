"""
Import por upload de XLSX: endpoint → staging → tool (docs/PLANO_XLSX.md, Blocos 2 e 3).

O que estes testes protegem, além do caminho feliz: a tool NUNCA grava (guardrail 4) e
o preview só existe depois de um upload.
"""
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.extrato import router as extrato_router
from app.tools import extrato_staging
from app.tools.extrato import tool_importar_extrato
from tests.gerador_extrato import (
    DATA_REFERENCIA_FIXTURE,
    PROVENTOS_LIQUIDOS_FIXTURE,
    TOTAL_POSICOES_FIXTURE,
    VARIACAO_MES_FIXTURE,
)
from tests.planilhas import bytes_fixture

logger = logging.getLogger(__name__)


@pytest.fixture
def client():
    """App mínimo com só o router de extrato — evita subir banco e seeds."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(extrato_router)
    extrato_staging.clear()
    yield TestClient(app)
    extrato_staging.clear()


def _upload(client):
    return client.post(
        "/extrato/upload",
        files={"arquivo": (
            "extrato_exemplo.xlsx",
            bytes_fixture(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )


def test_upload_devolve_preview(client):
    resp = _upload(client)
    assert resp.status_code == 200, resp.text

    preview = resp.json()
    assert preview["total_posicoes"] == TOTAL_POSICOES_FIXTURE
    assert preview["data_referencia"] == DATA_REFERENCIA_FIXTURE
    assert preview["source"] == "extrato_btg_xlsx"
    assert preview["checagem_totais"]["ok"] is True
    assert preview["proventos_do_mes"]["total_liquido"] == pytest.approx(
        PROVENTOS_LIQUIDOS_FIXTURE, abs=0.01
    )
    assert preview["comparativo_mes_anterior"]["variacao_reais"] == pytest.approx(
        VARIACAO_MES_FIXTURE, abs=0.01
    )
    assert "PREVIEW" in preview["aviso"]


def test_upload_rejeita_nao_xlsx(client):
    resp = client.post(
        "/extrato/upload",
        files={"arquivo": ("extrato.pdf", b"%PDF-1.4 conteudo", "application/pdf")},
    )
    assert resp.status_code == 400
    assert ".xlsx" in resp.json()["detail"]


def test_upload_rejeita_xlsx_corrompido(client):
    resp = client.post(
        "/extrato/upload",
        files={"arquivo": ("extrato.xlsx", b"nao sou um zip", "application/vnd.ms-excel")},
    )
    assert resp.status_code == 400


async def test_tool_sem_upload_orienta_o_usuario():
    """Sem arquivo enviado a tool não estoura: devolve {'error': ...} (guardrail 2)."""
    extrato_staging.clear()
    resultado = await tool_importar_extrato()

    assert "error" in resultado
    assert "Importar extrato" in resultado["error"]
    assert "posicoes" not in resultado


async def test_tool_le_o_upload(client):
    """Fluxo real: upload pela UI, depois o agente chama a tool sem argumentos."""
    assert _upload(client).status_code == 200

    resultado = await tool_importar_extrato()

    assert "error" not in resultado
    assert resultado["total_posicoes"] == TOTAL_POSICOES_FIXTURE
    assert resultado["arquivo"] == "extrato_exemplo.xlsx"
    assert resultado["recebido_em"]
    # O preview é só leitura — as posições vêm no formato aceito por gravar_posicoes.
    primeira = resultado["posicoes"][0]
    assert {"nome", "classe", "quantidade", "valor_mercado"} <= set(primeira)


def test_preview_endpoints(client):
    assert client.get("/extrato/preview").status_code == 404

    _upload(client)
    assert client.get("/extrato/preview").status_code == 200

    assert client.delete("/extrato/preview").status_code == 204
    assert client.get("/extrato/preview").status_code == 404
