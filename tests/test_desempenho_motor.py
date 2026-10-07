"""
Motor de desempenho (docs/PLANO_HISTORICO.md, Bloco 3) — funções puras.

Números de referência calculados à mão: o exemplo do plano (100.000 → PIX de 2.000 em 16/07
→ 103.000 = +0,9904%) e a fixture sintética (rentabilidade nas constantes do gerador).
"""
from datetime import date

import pytest

from app.tools.desempenho import (
    dietz,
    extrair_mes,
    janela,
    meses_entre,
    montar_serie,
    resumo,
)
from app.tools.lancamentos import APORTE, Regra
from tests.gerador_extrato import (
    PROVENTOS_LIQUIDOS_FIXTURE,
    PROVENTOS_POR_CLASSE_FIXTURE,
    RENTABILIDADE_PCT_FIXTURE,
    TOTAL_POSICOES_VALOR_FIXTURE,
    VARIACAO_MES_FIXTURE,
)
from tests.planilhas import bytes_fixture, payload_mes


def _mes(ref, v_ini, v_fim, **kw):
    return extrair_mes(ref, payload_mes(ref, v_ini, v_fim, **kw))


# ---------------------------------------------------------------------------
# Dietz
# ---------------------------------------------------------------------------

def test_dietz_exemplo_do_plano():
    r, ganho, base = dietz(100_000, 103_000, [("2026-07-16", 2_000)], date(2026, 6, 30), date(2026, 7, 31))
    assert ganho == pytest.approx(1_000)
    assert base == pytest.approx(100_000 + 2_000 * 15 / 31)
    assert r == pytest.approx(0.0099041, abs=1e-6)


def test_fluxo_no_ultimo_dia_nao_entra_na_base():
    r, _, base = dietz(100_000, 103_000, [("2026-07-31", 2_000)], date(2026, 6, 30), date(2026, 7, 31))
    assert base == pytest.approx(100_000)
    assert r == pytest.approx(0.01)


def test_base_nao_positiva_nao_vira_percentual():
    r, _, _ = dietz(0, 1_000, [("2026-07-10", 1_000)], date(2026, 6, 30), date(2026, 7, 31))
    assert r is not None   # aporte no dia 10 dá base positiva...
    r, _, _ = dietz(0, 1_000, [("2026-07-31", 1_000)], date(2026, 6, 30), date(2026, 7, 31))
    assert r is None       # ...mas conta aberta no último dia não tem base


# ---------------------------------------------------------------------------
# Um mês
# ---------------------------------------------------------------------------

def test_mes_da_fixture():
    from app.tools.btg_xlsx_parser import parse_btg_xlsx

    extrato = parse_btg_xlsx(bytes_fixture())
    mes = extrair_mes(extrato.data_referencia, extrato.to_dict())
    assert mes["status"] == "ok"
    assert mes["mes"] == "2026-07"
    assert mes["rentabilidade_pct"] == pytest.approx(RENTABILIDADE_PCT_FIXTURE, abs=1e-4)
    assert mes["ganho"] == pytest.approx(VARIACAO_MES_FIXTURE)
    assert mes["aportes"] == 0.0 and mes["resgates"] == 0.0
    assert mes["patrimonio_posicoes_fim"] == pytest.approx(TOTAL_POSICOES_VALOR_FIXTURE, abs=0.01)
    assert mes["proventos"]["total"] == pytest.approx(PROVENTOS_LIQUIDOS_FIXTURE)
    assert mes["proventos"]["por_classe"] == PROVENTOS_POR_CLASSE_FIXTURE


def test_aporte_do_razao_sai_da_rentabilidade():
    mes = _mes("2026-07-31", 100_000, 103_000, lancamentos=[("2026-07-16", "PIX RECEBIDO", 2_000)])
    assert mes["status"] == "ok"
    assert mes["aportes"] == 2_000
    assert mes["rentabilidade_pct"] == pytest.approx(0.9904, abs=1e-4)
    assert mes["variacao_saldo"] == pytest.approx(3_000), "a variação de saldo continua disponível"


def test_lancamento_desconhecido_deixa_o_mes_provisorio_ate_a_regra():
    lanc = [("2026-07-16", "CREDITO MISTERIOSO", 2_000)]
    provisorio = _mes("2026-07-31", 100_000, 103_000, lancamentos=lanc)
    assert provisorio["status"] == "provisorio"
    assert provisorio["motivos"] == ["nao_classificados"]
    assert provisorio["rentabilidade_pct"] == pytest.approx(3.0), "pendente conta como interno"

    regra = Regra(tipo=APORTE, modo="prefixo", padrao="credito misterioso", id=1)
    resolvido = extrair_mes("2026-07-31", payload_mes("2026-07-31", 100_000, 103_000, lancamentos=lanc), [regra])
    assert resolvido["status"] == "ok"
    assert resolvido["rentabilidade_pct"] == pytest.approx(0.9904, abs=1e-4)


def test_razao_que_nao_fecha_deixa_provisorio():
    mes = _mes("2026-07-31", 100_000, 101_000, razao_ok=False)
    assert mes["status"] == "provisorio"
    assert mes["motivos"] == ["razao_nao_fecha"]


def test_arquivo_v1_nao_tem_rentabilidade_mas_tem_saldo():
    mes = _mes("2026-07-31", 100_000, 103_000, versao=1)
    assert mes["status"] == "sem_lancamentos"
    assert mes["rentabilidade_pct"] is None
    assert mes["variacao_saldo"] == pytest.approx(3_000)


def test_primeiro_mes_da_conta_fica_sem_base():
    assert _mes("2026-07-31", 0, 5_000)["status"] == "sem_base"


def test_periodo_que_nao_e_mes_civil_fica_de_fora():
    mes = _mes("2026-08-10", 45_000.00, 45_100, periodo_inicio="2026-08-01")
    assert mes["status"] == "periodo_parcial"


def test_fluxo_grande_avisa_que_e_aproximacao():
    mes = _mes("2026-07-31", 10_000, 25_000, lancamentos=[("2026-07-15", "PIX RECEBIDO", 15_000)])
    assert "fluxo_relevante" in mes["avisos"]


def test_payload_antigo_sem_sumario_usa_o_comparativo():
    """Arquivamento manual guardava o preview, que não tem o Sumário."""
    preview = {
        "data_referencia": "2026-07-31",
        "posicoes": [],
        "comparativo_mes_anterior": {
            "data_atual": "2026-07-31", "data_anterior": "2026-06-30",
            "saldo_bruto_atual": 45_500.00, "saldo_bruto_anterior": 45_000.00,
        },
        "proventos_do_mes": {"itens": [{"ticker": "KNCR11", "valor_liquido": 60.0, "transacao": "RENDIMENTO"}]},
    }
    mes = extrair_mes("2026-07-31", preview)
    assert mes["status"] == "sem_lancamentos"
    assert mes["variacao_saldo"] == pytest.approx(500.00)
    assert mes["proventos"]["total"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Proventos
# ---------------------------------------------------------------------------

def test_amortizacao_fica_fora_da_renda():
    mes = _mes("2026-07-31", 100_000, 100_500, proventos=[
        {"ticker": "KNCR11", "classe": "FII", "valor_liquido": 60.0, "amortizacao": False},
        {"ticker": "KNCR11", "classe": "FII", "valor_liquido": 40.0, "amortizacao": True},
    ])
    assert mes["proventos"]["total"] == pytest.approx(60.0)
    assert mes["proventos"]["amortizacao"] == pytest.approx(40.0)


def test_provento_que_aparece_na_rv_e_no_razao_conta_uma_vez():
    mes = _mes(
        "2026-07-31", 100_000, 100_500,
        proventos=[{"ticker": "KNCR11", "classe": "FII", "valor_liquido": 60.0}],
        lancamentos=[
            ("2026-07-13", "RENDIMENTOS - À VISTA s/ FII KINEA RICI - KNCR11", 60.0),
            ("2026-07-15", "JUROS CUPOM TESOURO IPCA 2029", 150.0),
            ("2026-07-20", "ALUGUEL DE ACOES TAEE11", 3.5),
        ],
    )
    p = mes["proventos"]
    assert p["proventos"] == pytest.approx(60.0 + 150.0), "o cupom do Tesouro só existe no razão"
    assert p["por_classe"]["TESOURO"] == pytest.approx(150.0)
    assert p["aluguel"] == pytest.approx(3.5)
    assert p["total"] == pytest.approx(60.0 + 150.0 + 3.5)


# ---------------------------------------------------------------------------
# Série e janelas
# ---------------------------------------------------------------------------

def test_meses_entre():
    assert meses_entre("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_mes_que_falta_vira_lacuna_e_continuidade_e_conferida():
    serie, _ = montar_serie([
        _mes("2026-05-31", 100_000, 101_000),
        _mes("2026-07-31", 101_500, 102_000),   # junho não arquivado
        _mes("2026-08-31", 102_500, 103_000),   # V_ini ≠ V_fim de julho
    ])
    assert [m["mes"] for m in serie] == ["2026-05", "2026-06", "2026-07", "2026-08"]
    assert serie[1]["status"] == "lacuna"
    assert "continuidade" not in serie[2]["avisos"], "depois de lacuna não há com quem comparar"
    assert "continuidade" in serie[3]["avisos"]


def test_extrato_parcial_nao_ocupa_o_lugar_do_mes_completo():
    serie, parciais = montar_serie([
        _mes("2026-08-10", 100_000, 100_100, periodo_inicio="2026-08-01"),
        _mes("2026-08-31", 100_000, 101_000),
    ])
    assert len(serie) == 1 and serie[0]["data_referencia"] == "2026-08-31"
    assert [p["data_referencia"] for p in parciais] == ["2026-08-10"]


def test_encadeamento_e_benchmarks():
    """1% e 2% = 3,02%; CDI 1,0% e 1,1% = 2,111% → 143,06% do CDI; IPCA 0,5% e −0,3% → real 2,816%."""
    serie, _ = montar_serie([
        _mes("2026-07-31", 100_000, 101_000),
        _mes("2026-08-31", 101_000, 103_020),
    ])
    j = janela(serie, "inicio", cdi={"2026-07": 1.0, "2026-08": 1.1}, ipca={"2026-07": 0.5, "2026-08": -0.3})
    assert j["rentabilidade_pct"] == pytest.approx(3.02, abs=1e-4)
    assert j["cdi_pct"] == pytest.approx(2.111, abs=1e-4)
    assert j["pct_do_cdi"] == pytest.approx(143.06, abs=0.01)
    assert j["ipca_pct"] == pytest.approx(0.1985, abs=1e-4)
    assert j["retorno_real_pct"] == pytest.approx(2.8159, abs=1e-3)
    assert j["parcial"] is False and j["provisorio"] is False


def test_janela_parcial_e_ipca_pendente():
    serie, _ = montar_serie([
        _mes("2026-06-30", 100_000, 101_000),
        _mes("2026-07-31", 101_000, 102_000, versao=1),   # sem razão: fora da conta
        _mes("2026-08-31", 102_000, 103_000),
    ])
    j = janela(serie, "ano", cdi={"2026-06": 1.0, "2026-08": 1.0}, ipca={"2026-06": 0.3})
    assert j["de"] == "2026-01" and j["ate"] == "2026-08"
    assert j["considerados"] == ["2026-06", "2026-08"]
    assert "2026-07" in j["faltantes"] and "2026-01" in j["faltantes"]
    assert j["parcial"] is True
    assert j["cdi_pct"] is not None
    assert j["ipca_pct"] is None and j["ipca_pendente"] == ["2026-08"]


def test_janela_provisoria_quando_algum_mes_e():
    serie, _ = montar_serie([
        _mes("2026-07-31", 100_000, 101_000, lancamentos=[("2026-07-10", "CREDITO MISTERIOSO", 10)]),
    ])
    assert janela(serie, "mes")["provisorio"] is True


def test_anualizado_so_com_doze_meses_ou_mais():
    meses = []
    v = 100_000.0
    for m in meses_entre("2025-08", "2026-07"):
        ano, mm = int(m[:4]), int(m[5:])
        fim = date(ano + (mm // 12), mm % 12 + 1, 1)
        ref = date.fromordinal(fim.toordinal() - 1).isoformat()
        meses.append(_mes(ref, v, v * 1.01))
        v *= 1.01
    serie, _ = montar_serie(meses)
    j = janela(serie, "inicio")
    assert len(j["considerados"]) == 12
    assert j["anualizado_pct"] == pytest.approx(j["rentabilidade_pct"], abs=1e-3)
    assert janela(serie, "12m")["anualizado_pct"] is None


def test_resumo_vazio_e_completo():
    assert resumo([])["vazio"] is True

    r = resumo(
        [_mes("2026-07-31", 100_000, 101_000, proventos=[{"ticker": "KNCR11", "classe": "FII", "valor_liquido": 60.0}],
              posicoes=[{"ticker": "KNCR11", "classe": "FII", "valor_mercado": 6000.0,
                         "preco_medio": 95.0, "quantidade": 60}])],
        posicoes_atuais=[{"ticker": "KNCR11", "classe": "FII", "valor_mercado": 6000.0,
                          "preco_medio": 95.0, "quantidade": 60}],
        cdi={"2026-07": 1.2152},
    )
    assert r["vazio"] is False
    assert r["ultimo_fechamento"] == "2026-07-31"
    assert set(r["janelas"]) == {"mes", "ano", "12m", "inicio"}
    assert r["meses"][0]["pct_do_cdi"] == pytest.approx(1.0 / 1.2152 * 100, abs=0.01)
    ativo = r["proventos"]["por_ativo_12m"][0]
    assert ativo["yield_pct"] == pytest.approx(1.0)
    assert ativo["yield_sobre_custo_pct"] == pytest.approx(60 / (95 * 60) * 100, abs=0.01)
