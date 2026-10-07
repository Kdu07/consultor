"""
GET /desempenho (docs/PLANO_HISTORICO.md, Bloco 3) — com banco isolado e sem rede.
"""
import json
from datetime import date

import pytest

from tests.gerador_extrato import PROVENTOS_LIQUIDOS_FIXTURE, RENTABILIDADE_PCT_FIXTURE
from tests.planilhas import bytes_fixture, payload_mes


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")
    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    import app.models  # noqa: F401
    import app.tools.gravar as gravar_mod
    from sqlmodel import SQLModel

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(gravar_mod, "engine", engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    get_settings.cache_clear()


@pytest.fixture
def cliente():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.desempenho import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _arquivar(engine, payload: dict):
    from sqlmodel import Session
    from app.models.extrato import ExtratoImportado

    with Session(engine) as s:
        s.add(ExtratoImportado(
            data_referencia=date.fromisoformat(payload["data_referencia"]),
            payload_json=json.dumps(payload, ensure_ascii=False),
        ))
        s.commit()


def test_sem_nada_arquivado(banco, cliente):
    resp = cliente.get("/desempenho")
    assert resp.status_code == 200, resp.text
    assert resp.json()["vazio"] is True


async def test_mes_importado_pelo_chat_aparece_no_desempenho(banco, cliente):
    from app.tools import extrato_staging
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.extrato import montar_preview
    from app.tools.gravar import tool_gravar_posicoes

    extrato = parse_btg_xlsx(bytes_fixture())
    extrato_staging.set_preview(montar_preview(extrato, "x.xlsx"), "x.xlsx", bruto=extrato.to_dict())
    try:
        await tool_gravar_posicoes()
    finally:
        extrato_staging.clear()

    corpo = cliente.get("/desempenho").json()
    assert corpo["vazio"] is False
    assert corpo["ultimo_fechamento"] == "2026-07-31"
    julho = corpo["meses"][0]
    assert julho["status"] == "ok"
    assert julho["rentabilidade_pct"] == pytest.approx(RENTABILIDADE_PCT_FIXTURE, abs=1e-3)
    assert corpo["janelas"]["mes"]["rentabilidade_pct"] == pytest.approx(RENTABILIDADE_PCT_FIXTURE, abs=1e-3)
    assert corpo["proventos"]["por_mes"][0]["total"] == pytest.approx(PROVENTOS_LIQUIDOS_FIXTURE)
    assert corpo["fonte"]


def test_tres_meses_encadeados_e_regra_do_dono(banco, cliente):
    _arquivar(banco, payload_mes("2026-05-31", 100_000, 101_000))
    _arquivar(banco, payload_mes("2026-06-30", 101_000, 103_020,
                                 lancamentos=[("2026-06-15", "CREDITO MISTERIOSO", 1_000)]))
    _arquivar(banco, payload_mes("2026-07-31", 103_020, 104_050.20))

    corpo = cliente.get("/desempenho").json()
    junho = next(m for m in corpo["meses"] if m["mes"] == "2026-06")
    assert junho["status"] == "provisorio"
    assert corpo["pendencias"]["nao_classificados"] == 1
    assert corpo["janelas"]["inicio"]["provisorio"] is True

    # O dono diz que aquele crédito foi um aporte: junho passa a ok, sem reimportar nada.
    from sqlmodel import Session
    from app.tools import regras_lancamento
    with Session(banco) as s:
        regras_lancamento.criar_ou_atualizar(s, tipo="APORTE", padrao="credito misterioso")
        s.commit()

    corpo = cliente.get("/desempenho").json()
    junho = next(m for m in corpo["meses"] if m["mes"] == "2026-06")
    assert junho["status"] == "ok"
    assert junho["aportes"] == pytest.approx(1_000)
    assert corpo["janelas"]["inicio"]["provisorio"] is False
    assert corpo["janelas"]["inicio"]["considerados"] == ["2026-05", "2026-06", "2026-07"]


def test_preview_traz_a_rentabilidade_do_mes():
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.extrato import montar_preview

    preview = montar_preview(parse_btg_xlsx(bytes_fixture()), "x.xlsx")
    r = preview["rentabilidade_do_mes"]
    assert r["status"] == "ok"
    assert r["pct"] == pytest.approx(RENTABILIDADE_PCT_FIXTURE, abs=1e-3)
    assert "rentabilidade_do_mes" in preview["comparativo_mes_anterior"]["nota"]
