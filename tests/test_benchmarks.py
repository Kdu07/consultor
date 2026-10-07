"""
Benchmarks do BCB (docs/PLANO_HISTORICO.md, Bloco 4) — sem rede: a SGS é simulada com
httpx.MockTransport e cada consulta fica registrada para conferir o que foi pedido.
"""
from datetime import date, datetime, timedelta

import httpx
import pytest

from app.tools import benchmarks


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")
    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    import app.models  # noqa: F401
    from sqlmodel import SQLModel

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    get_settings.cache_clear()


def _dias_uteis(inicio: date, fim: date):
    d = inicio
    while d <= fim:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


class SGSFalsa:
    """CDI diário de 0,05% a.d. em todo dia útil até `ultima_cdi`; IPCA fixo por mês."""

    def __init__(self, ultima_cdi: date, ipca: dict[str, float], html: bool = False):
        self.ultima_cdi = ultima_cdi
        self.ipca = ipca
        self.html = html
        self.consultas: list[tuple[int, date, date]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.html:
            return httpx.Response(200, text="<html><title>Requisição inválida!</title></html>",
                                  headers={"content-type": "text/html"})
        serie = int(request.url.path.split("bcdata.sgs.")[1].split("/")[0])
        ini = datetime.strptime(request.url.params["dataInicial"], "%d/%m/%Y").date()
        fim = datetime.strptime(request.url.params["dataFinal"], "%d/%m/%Y").date()
        self.consultas.append((serie, ini, fim))
        if serie == 12:
            if (fim - ini).days > 3653:
                return httpx.Response(406, json={"error": "janela de no máximo 10 anos"})
            dados = [{"data": d.strftime("%d/%m/%Y"), "valor": "0.050000"}
                     for d in _dias_uteis(ini, min(fim, self.ultima_cdi))]
        else:
            dados = [{"data": f"01/{m[5:]}/{m[:4]}", "valor": str(v)}
                     for m, v in sorted(self.ipca.items())
                     if ini <= date(int(m[:4]), int(m[5:]), 1) <= fim]
        if not dados:
            return httpx.Response(404, json={"erro": {"statusCode": 404, "detail": "Value(s) not found"}})
        return httpx.Response(200, json=dados)


@pytest.fixture
def sgs(monkeypatch):
    def instalar(**kw) -> SGSFalsa:
        falsa = SGSFalsa(**kw)
        monkeypatch.setattr(benchmarks, "_novo_cliente",
                            lambda: httpx.AsyncClient(transport=httpx.MockTransport(falsa)))
        return falsa
    return instalar


def _cdi_esperado(mes_ini: date, mes_fim: date) -> float:
    """Composição independente: dias úteis em [véspera do mês, último dia do mês)."""
    n = sum(1 for d in _dias_uteis(mes_ini - timedelta(days=1), mes_fim - timedelta(days=1)))
    return round(((1.0005 ** n) - 1) * 100, 4)


async def test_cdi_composto_na_janela_do_extrato(banco, sgs):
    from sqlmodel import Session

    sgs(ultima_cdi=date(2026, 10, 2), ipca={"2026-07": 0.07, "2026-08": -0.32})
    with Session(banco) as s:
        r = await benchmarks.garantir_indicadores(s, ["2026-07", "2026-08"], hoje=date(2026, 10, 5))
    assert r["cdi"]["2026-07"] == pytest.approx(_cdi_esperado(date(2026, 7, 1), date(2026, 7, 31)))
    assert r["cdi"]["2026-08"] == pytest.approx(_cdi_esperado(date(2026, 8, 1), date(2026, 8, 31)))
    assert r["ipca"] == {"2026-07": 0.07, "2026-08": -0.32}
    assert r["status"] == "ok"


async def test_mes_em_cache_nao_vai_ao_bcb(banco, sgs):
    from sqlmodel import Session

    falsa = sgs(ultima_cdi=date(2026, 10, 2), ipca={"2026-07": 0.07})
    with Session(banco) as s:
        await benchmarks.garantir_indicadores(s, ["2026-07"], hoje=date(2026, 10, 5))
        n = len(falsa.consultas)
        benchmarks.limpar_estado()
        r = await benchmarks.garantir_indicadores(s, ["2026-07"], hoje=date(2026, 10, 5))
    assert len(falsa.consultas) == n, "mês fechado em cache não pode gerar nova consulta"
    assert r["status"] == "ok"


async def test_ipca_ainda_nao_publicado_fica_pendente_e_nao_insiste(banco, sgs):
    from sqlmodel import Session

    falsa = sgs(ultima_cdi=date(2026, 10, 2), ipca={"2026-08": -0.32})   # setembro não saiu
    with Session(banco) as s:
        r = await benchmarks.garantir_indicadores(s, ["2026-08", "2026-09"], hoje=date(2026, 10, 5))
        assert r["status"] == "parcial"
        assert "2026-09" in r["cdi"] and "2026-09" not in r["ipca"]
        consultas_ipca = sum(1 for c in falsa.consultas if c[0] == 433)

        await benchmarks.garantir_indicadores(s, ["2026-08", "2026-09"], hoje=date(2026, 10, 5))
        assert sum(1 for c in falsa.consultas if c[0] == 433) == consultas_ipca, "esperar antes de tentar de novo"


async def test_mes_corrente_e_mes_sem_fechamento_nao_entram(banco, sgs):
    from sqlmodel import Session

    sgs(ultima_cdi=date(2026, 9, 25), ipca={})   # CDI publicado só até 25/09
    with Session(banco) as s:
        r = await benchmarks.garantir_indicadores(s, ["2026-09", "2026-10"], hoje=date(2026, 10, 5))
    assert r["cdi"] == {}, "setembro sem taxa depois do fechamento ainda não acabou"
    assert r["status"] == "parcial"


async def test_html_de_erro_vira_indisponivel_sem_levantar(banco, sgs):
    from sqlmodel import Session

    sgs(ultima_cdi=date(2026, 10, 2), ipca={}, html=True)
    with Session(banco) as s:
        r = await benchmarks.garantir_indicadores(s, ["2026-07"], hoje=date(2026, 10, 5))
    assert r["status"] == "indisponivel"
    assert r["cdi"] == {}
    assert "JSON" in r["erro"]


async def test_consulta_longa_e_fatiada_em_menos_de_dez_anos(banco, sgs):
    from sqlmodel import Session
    from app.tools.desempenho import meses_entre

    falsa = sgs(ultima_cdi=date(2026, 10, 2), ipca={})
    with Session(banco) as s:
        r = await benchmarks.garantir_indicadores(s, meses_entre("2012-01", "2026-08"), hoje=date(2026, 10, 5))
    diarias = [c for c in falsa.consultas if c[0] == 12]
    assert len(diarias) >= 2
    assert all((fim - ini).days <= 3653 for _, ini, fim in diarias)
    assert len(r["cdi"]) == len(meses_entre("2012-01", "2026-08"))


def test_rota_responde_mesmo_com_o_bcb_fora(banco, sgs):
    """O BCB fora do ar tira os benchmarks, não a página."""
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    from app.api.desempenho import router
    from app.models.extrato import ExtratoImportado
    from tests.planilhas import payload_mes

    sgs(ultima_cdi=date(2026, 10, 2), ipca={}, html=True)
    with Session(banco) as s:
        s.add(ExtratoImportado(data_referencia=date(2026, 7, 31),
                               payload_json=json.dumps(payload_mes("2026-07-31", 100_000, 101_000))))
        s.commit()

    app = FastAPI()
    app.include_router(router)
    corpo = TestClient(app).get("/desempenho").json()
    assert corpo["benchmarks"]["status"] == "indisponivel"
    assert corpo["meses"][0]["rentabilidade_pct"] == pytest.approx(1.0)
    assert corpo["meses"][0]["cdi_pct"] is None
