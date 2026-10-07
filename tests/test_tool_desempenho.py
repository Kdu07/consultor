"""
Tool desempenho_carteira (docs/PLANO_HISTORICO.md, Bloco 6).

O que importa para o modelo: o número vem com o período e com o porquê quando não é
definitivo, a saída é curta (vai inteira para o contexto) e nada levanta exceção.
"""
import json
from datetime import date

import pytest

from tests.planilhas import payload_mes


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


def _arquivar(engine, *payloads):
    from sqlmodel import Session
    from app.models.extrato import ExtratoImportado

    with Session(engine) as s:
        for p in payloads:
            s.add(ExtratoImportado(data_referencia=date.fromisoformat(p["data_referencia"]),
                                   payload_json=json.dumps(p)))
        s.commit()


def _indices(engine, cdi: dict, ipca: dict):
    """Benchmarks já em cache — a tool não vai à rede nos testes."""
    from sqlmodel import Session
    from app.models.indicador_mensal import IndicadorMensal

    with Session(engine) as s:
        for mes, v in cdi.items():
            s.add(IndicadorMensal(serie="CDI", mes=mes, valor_pct=v, fonte="sgs12"))
        for mes, v in ipca.items():
            s.add(IndicadorMensal(serie="IPCA", mes=mes, valor_pct=v, fonte="sgs433"))
        s.commit()


async def test_sem_extrato_e_erro_de_tool(banco):
    from app.tools.desempenho_servico import tool_desempenho_carteira

    r = await tool_desempenho_carteira()
    assert "error" in r and "Histórico" in r["error"]


async def test_parametros_invalidos_viram_erro():
    from app.tools.desempenho_servico import tool_desempenho_carteira

    assert "error" in await tool_desempenho_carteira(periodo="semana")
    assert "error" in await tool_desempenho_carteira(nivel="planeta")
    assert "error" in await tool_desempenho_carteira(periodo="12m", mes="2026-07")
    assert "error" in await tool_desempenho_carteira(periodo="mes", mes="julho")


async def test_janela_com_benchmarks_e_avisos(banco):
    from app.tools.desempenho_servico import tool_desempenho_carteira

    _arquivar(
        banco,
        payload_mes("2026-06-30", 100_000, 101_000),
        payload_mes("2026-07-31", 101_000, 103_020,
                    lancamentos=[("2026-07-20", "CREDITO MISTERIOSO", 500)]),
        payload_mes("2026-08-31", 103_020, 104_000, versao=1),   # sem razão
    )
    _indices(banco, cdi={"2026-06": 1.0, "2026-07": 1.1, "2026-08": 1.0}, ipca={"2026-06": 0.2})

    r = await tool_desempenho_carteira(periodo="ano")
    assert r["as_of"] == "2026-08-31"
    assert r["periodo"]["de"] == "2026-01" and r["periodo"]["ate"] == "2026-08"
    assert r["periodo"]["considerados"] == 2
    assert r["status"] == "provisorio"
    assert r["cdi_pct"] == pytest.approx(2.111, abs=1e-3)
    assert "ipca_pct" not in r, "sem IPCA de julho não há IPCA acumulado — campo omitido"
    texto = " ".join(r["avisos"])
    assert "ago/26 (arquivo antigo" in texto
    assert "Provisório" in texto and "jul/26" in texto
    assert "IPCA de jul/26" in texto
    assert r["mensal_colunas"][0] == "mes"
    assert [linha[0] for linha in r["mensal"]][-3:] == ["2026-06", "2026-07", "2026-08"]
    assert len(json.dumps(r, ensure_ascii=False).encode("utf-8")) < 2500


async def test_mes_especifico(banco):
    from app.tools.desempenho_servico import tool_desempenho_carteira

    _arquivar(banco, payload_mes("2026-06-30", 100_000, 101_000), payload_mes("2026-07-31", 101_000, 102_000))
    _indices(banco, cdi={"2026-06": 1.0, "2026-07": 1.0}, ipca={"2026-06": 0.2, "2026-07": 0.1})

    r = await tool_desempenho_carteira(periodo="mes", mes="2026-06")
    assert r["periodo"]["de"] == r["periodo"]["ate"] == "2026-06"
    assert r["rentabilidade_pct"] == pytest.approx(1.0)
    assert r["pct_do_cdi"] == pytest.approx(100.0)
    assert r["status"] == "ok"


async def test_dispatch_do_agente_nunca_levanta(banco, monkeypatch):
    from app.agent import loop
    from app.tools import desempenho_servico

    async def explode(*a, **k):
        raise RuntimeError("banco sumiu")

    monkeypatch.setattr(desempenho_servico, "desempenho_completo", explode)
    r = await loop._dispatch("desempenho_carteira", {})
    assert "error" in r


def test_tool_registrada():
    from app.agent.loop import _TOOL_DISPATCH
    from app.tools.schemas import TOOL_DEFINITIONS

    nomes = {t["name"] for t in TOOL_DEFINITIONS}
    assert "desempenho_carteira" in nomes
    assert nomes == set(_TOOL_DISPATCH)


def _junho_e_julho_da_fixture() -> tuple[dict, dict]:
    """Julho = a fixture sintética; junho = a mesma carteira mais barata, fechando no
    patrimônio que o Sumário de julho dá como anterior."""
    import copy

    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from tests.planilhas import bytes_fixture

    julho = parse_btg_xlsx(bytes_fixture()).to_dict()
    junho = copy.deepcopy(julho)
    v_ini_julho = julho["sumario"]["anterior"]["total"]["bruto"]
    escala = v_ini_julho / julho["sumario"]["atual"]["total"]["bruto"]
    junho["data_referencia"] = "2026-06-30"
    junho["sumario"]["atual"]["data"] = "2026-06-30"
    junho["sumario"]["atual"]["total"] = {"bruto": v_ini_julho, "liquido": v_ini_julho}
    junho["sumario"]["anterior"]["data"] = "2026-05-31"
    junho["sumario"]["anterior"]["total"] = {"bruto": round(v_ini_julho * 0.99, 2), "liquido": None}
    junho["sumario"]["meta"]["periodo_inicio"] = "2026-06-01"
    for p in junho["posicoes"]:
        p["valor_mercado"] = round(p["valor_mercado"] * escala, 2)
    return junho, julho


async def test_nivel_ativo_traz_classes_e_os_10_maiores_em_menos_de_3kb(banco):
    from app.tools.desempenho_servico import tool_desempenho_carteira

    _arquivar(banco, *_junho_e_julho_da_fixture())
    _indices(banco, cdi={"2026-06": 1.0, "2026-07": 1.2}, ipca={"2026-06": 0.2, "2026-07": 0.3})

    r = await tool_desempenho_carteira(periodo="12m", nivel="ativo")
    assert r["classes_colunas"][:2] == ["classe", "valor_fim_rs"]
    assert {linha[0] for linha in r["classes"]} >= {"ACAO", "FII", "TESOURO"}
    assert len(r["ativos"]) == 10
    assert r["ativos_omitidos"] == 4
    resultados = [abs(linha[3] or 0) for linha in r["ativos"]]
    assert resultados == sorted(resultados, reverse=True)
    assert len(json.dumps(r, ensure_ascii=False).encode("utf-8")) < 3000

    so_classes = await tool_desempenho_carteira(periodo="mes", nivel="classe")
    assert so_classes["classes"] and "ativos" not in so_classes
    assert so_classes["composicao_periodo"] == "2026-07 a 2026-07"

    total = await tool_desempenho_carteira(periodo="mes")
    assert "classes" not in total
