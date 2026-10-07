"""
Composição por classe e por ativo, comparação de fechamentos e CSV (docs/PLANO_HISTORICO.md,
Bloco 9). Payloads montados à mão: as linhas imitam o formato do BTG, nenhuma vem de extrato
de verdade.
"""
import json
import re
from datetime import date, timedelta

import pytest

from app.tools.composicao import acumular, comparar, composicao_mes, historico_do_papel
from app.tools.desempenho import extrair_mes
from app.tools.lancamentos import APORTE_EM_ATIVOS, EVENTO_SOCIETARIO, Regra, ativo_ref

INI, FIM = date(2026, 6, 30), date(2026, 7, 31)
SELIC = "TD:LFT:2031-03-01"
IPCA35 = "TD:NTNB-P:2035-05-15"


# ---------------------------------------------------------------------------
# Payloads sintéticos
# ---------------------------------------------------------------------------

def _pos(chave: str, classe: str, q: float, preco: float, nome: str | None = None) -> dict:
    ticker = chave.split(":", 1)[1] if chave.startswith("B3:") else nome
    return {
        "chave_externa": chave, "classe": classe, "ticker": ticker, "nome": nome or ticker,
        "quantidade": q, "preco_fechamento": preco, "valor_mercado": round(q * preco, 2),
    }


def _selic(q: float, preco: float) -> dict:
    return _pos(SELIC, "TESOURO", q, preco, nome="Tesouro Selic 2031")


def _ipca35(q: float, preco: float) -> dict:
    return _pos(IPCA35, "TESOURO", q, preco, nome="Tesouro IPCA+ 2035")


def _caixa(valor: float) -> dict:
    return {"chave_externa": "CAIXA:BTG", "classe": "CAIXA", "ticker": None, "nome": "Conta corrente",
            "quantidade": 1, "preco_fechamento": None, "valor_mercado": valor}


def _compra(ticker: str, data: str, q: float, valor: float) -> dict:
    return {"data": data, "transacao": "COMPRA", "ticker": ticker, "quantidade": q,
            "valor_liquido": -valor, "operacao": "COMPRA"}


def _venda(ticker: str, data: str, q: float, valor: float) -> dict:
    return {"data": data, "transacao": "VENDA", "ticker": ticker, "quantidade": q,
            "valor_liquido": valor, "operacao": "VENDA"}


def _provento(ticker: str, data: str, valor: float, q: float | None = None) -> dict:
    return {"data": data, "transacao": "DIVIDENDOS", "ticker": ticker, "quantidade": q,
            "valor_liquido": valor, "operacao": "PROVENTO", "amortizacao": False}


def _payload(
    ref: str,
    posicoes: list[dict],
    *,
    movimentacoes: list[dict] = (),
    proventos: list[dict] = (),
    lotes: list[dict] = (),
    lancamentos: list[tuple[str, str, float]] = (),
    versao: int = 2,
    v_ini: float | None = None,
    v_fim: float | None = None,
) -> dict:
    """Extrato arquivado de um mês civil. V_fim padrão = soma das posições."""
    fim = date.fromisoformat(ref)
    inicio = fim.replace(day=1)
    if v_fim is None:
        v_fim = round(sum(p["valor_mercado"] for p in posicoes), 2)
    payload = {
        "data_referencia": ref,
        "posicoes": [dict(p) for p in posicoes],
        "movimentacoes": [dict(m) for m in movimentacoes],
        "proventos": [dict(p) for p in proventos],
        "sumario": {
            "atual": {"data": ref, "mercados": {}, "total": {"bruto": v_fim, "liquido": v_fim}},
            "anterior": {"data": (inicio - timedelta(days=1)).isoformat(), "mercados": {},
                         "total": {"bruto": v_ini, "liquido": v_ini}},
            "meta": {"periodo_inicio": inicio.isoformat(), "emitido_em": None},
        },
        "checagem": {"ok": True},
    }
    if versao >= 2:
        payload["versao_parser"] = versao
        payload["lotes_rf"] = [dict(l) for l in lotes]
        payload["lancamentos_conta"] = [
            {"seq": i, "data": d, "descricao": desc, "valor": v, "saldo": None}
            for i, (d, desc, v) in enumerate(lancamentos)
        ]
        payload["checagem"]["conta_corrente"] = {"ok": True}
    return payload


def _bbas3_julho() -> tuple[dict, dict]:
    """O exemplo do plano: 100 × 20,00 → compra de 50 em 10/07 por 1.050,30 (paga com um PIX
    do mesmo dia) → provento de 10,00 em 20/07 (data-com antes da compra) → fecha a 22,00."""
    junho = _payload("2026-06-30", [_pos("B3:BBAS3", "ACAO", 100, 20.0), _caixa(0.0)], v_ini=1900.0)
    julho = _payload(
        "2026-07-31", [_pos("B3:BBAS3", "ACAO", 150, 22.0), _caixa(10.0)],
        movimentacoes=[_compra("BBAS3", "2026-07-10", 50, 1050.30)],
        proventos=[_provento("BBAS3", "2026-07-20", 10.0, q=100)],
        lancamentos=[
            ("2026-07-10", "PIX RECEBIDO", 1050.30),
            ("2026-07-10", "LIQUIDACAO BOVESPA", -1050.30),
            ("2026-07-20", "DIVIDENDOS BBAS3", 10.0),
        ],
        v_ini=2000.0,
    )
    return junho, julho


def _papel(comp: dict, chave: str) -> dict:
    return next(a for a in comp["ativos"] if a["chave"] == chave)


# ---------------------------------------------------------------------------
# Por ativo e por classe
# ---------------------------------------------------------------------------

def test_exemplo_bbas3_do_plano():
    junho, julho = _bbas3_julho()
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)

    papel = _papel(comp, "B3:BBAS3")
    assert papel["status"] == "ok"
    assert papel["compras"] == 1050.30
    assert papel["renda"] == 10.0
    assert papel["resultado"] == 259.70
    assert papel["rentabilidade_pct"] == pytest.approx(10.5, abs=1e-4)      # TWR por preço

    acoes = comp["classes"][0]
    assert acoes["classe"] == "ACAO"
    assert acoes["resultado"] == 259.70
    assert round(acoes["rentabilidade_pct"], 2) == 9.59                      # Dietz da classe


def test_lote_novo_de_tesouro_entra_como_compra():
    junho = _payload("2026-06-30", [_selic(1.0, 15000.0)])
    julho = _payload(
        "2026-07-31", [_selic(1.5, 15150.0)],
        lotes=[
            {"chave_externa": SELIC, "aquisicao": "2024-01-10", "quantidade": 1.0, "valor_compra": 13000.0},
            {"chave_externa": SELIC, "aquisicao": "2026-07-15", "quantidade": 0.5, "valor_compra": 7530.0},
        ],
    )
    papel = _papel(composicao_mes("2026-07-31", julho, junho, INI, FIM), SELIC)
    assert papel["status"] == "ok"
    assert papel["compras"] == 7530.0
    assert papel["resultado"] == 195.0               # 22.725 − 15.000 − 7.530
    assert papel["rentabilidade_pct"] == pytest.approx(1.0)


def test_titulo_que_encolhe_sem_resgate_no_razao_fica_estimado():
    junho = _payload("2026-06-30", [_ipca35(2.0, 3000.0)])
    julho = _payload("2026-07-31", [_ipca35(1.0, 3030.0)])
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)
    papel = _papel(comp, IPCA35)
    assert papel["status"] == "estimado"
    assert papel["vendas"] == 3015.0                 # 1 × (3.000 + 3.030) / 2
    assert papel["resultado"] == 45.0
    assert papel["rentabilidade_pct"] == pytest.approx(1.0)
    assert comp["classes"][0]["status"] == "estimado"


def test_resgate_do_razao_casa_pelo_titulo_citado():
    junho = _payload("2026-06-30", [_ipca35(2.0, 3000.0), _selic(1.0, 15000.0)])
    julho = _payload(
        "2026-07-31", [_ipca35(1.0, 3030.0), _selic(1.0, 15100.0)],
        lancamentos=[("2026-07-20", "RESGATE TESOURO IPCA+ 2035", 3020.0)],
    )
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)
    papel = _papel(comp, IPCA35)
    assert papel["status"] == "ok"
    assert papel["vendas"] == 3020.0
    assert papel["resultado"] == 50.0
    assert _papel(comp, SELIC)["vendas"] == 0.0
    assert "resgate_sem_titulo" not in comp["avisos"]


def test_resgate_sem_titulo_casa_com_o_unico_que_encolheu():
    junho = _payload("2026-06-30", [_ipca35(2.0, 3000.0), _selic(1.0, 15000.0)])
    julho = _payload(
        "2026-07-31", [_ipca35(1.0, 3030.0), _selic(1.0, 15100.0)],
        lancamentos=[("2026-07-20", "RESGATE TESOURO DIRETO", 3020.0)],
    )
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)
    assert _papel(comp, IPCA35)["status"] == "ok"
    assert _papel(comp, IPCA35)["vendas"] == 3020.0
    assert "resgate_sem_titulo" not in comp["avisos"]


def test_desdobramento_detectado_pelo_preco():
    junho = _payload("2026-06-30", [_pos("B3:ITSA4", "ACAO", 100, 10.0)])
    julho = _payload("2026-07-31", [_pos("B3:ITSA4", "ACAO", 200, 5.2)])
    papel = _papel(composicao_mes("2026-07-31", julho, junho, INI, FIM), "B3:ITSA4")
    assert papel["status"] == "ok"
    assert papel["aviso"] == "evento_societario"
    assert papel["pendencia"] is None
    assert papel["resultado"] == 40.0
    assert papel["rentabilidade_pct"] == pytest.approx(4.0)  # 5,20 / (10,00 / 2) − 1


def test_quantidade_sem_negociacao_vira_pendencia_que_a_regra_resolve():
    junho = _payload("2026-06-30", [_pos("B3:TAEE11", "ACAO", 100, 10.0)])
    julho = _payload("2026-07-31", [_pos("B3:TAEE11", "ACAO", 110, 10.1)])

    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)
    papel = _papel(comp, "B3:TAEE11")
    assert papel["status"] == "pendente"
    assert papel["pendencia"] == "quantidade_sem_negociacao"
    assert papel["resultado"] is None
    assert comp["classes"][0]["resultado"] is None
    assert comp["transferencias"] == []

    regra = Regra(tipo=APORTE_EM_ATIVOS, escopo="ativo_mes", modo="exato",
                  padrao="B3:TAEE11", data_referencia="2026-07-31")
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM, [regra])
    papel = _papel(comp, "B3:TAEE11")
    assert papel["status"] == "ok"
    assert papel["aviso"] == "trazido_de_outra_corretora"
    assert papel["compras"] == 101.0                  # 10 × 10,10
    assert papel["resultado"] == 10.0
    assert papel["rentabilidade_pct"] == pytest.approx(1.0)
    assert comp["transferencias"] == [("2026-07-31", 101.0)]


def test_evento_societario_declarado_ajusta_o_preco_de_referencia():
    # Bonificação de 10% com o preço quase parado: o preço sozinho não convence, a regra sim
    junho = _payload("2026-06-30", [_pos("B3:BBDC4", "ACAO", 100, 10.0)])
    julho = _payload("2026-07-31", [_pos("B3:BBDC4", "ACAO", 110, 9.95)])
    regra = Regra(tipo=EVENTO_SOCIETARIO, escopo="ativo_mes", modo="exato",
                  padrao="B3:BBDC4", data_referencia="2026-07-31")
    papel = _papel(composicao_mes("2026-07-31", julho, junho, INI, FIM, [regra]), "B3:BBDC4")
    assert papel["status"] == "ok"
    assert papel["resultado"] == 94.5
    assert papel["rentabilidade_pct"] == pytest.approx(9.45)   # 9,95 / (10 / 1,1) − 1


def test_transferencia_de_ativos_entra_como_aporte_no_total():
    julho = _payload("2026-07-31", [_pos("B3:TAEE11", "ACAO", 110, 10.1)], v_ini=1000.0)
    mes = extrair_mes("2026-07-31", julho, fluxos_extras=[("2026-07-31", 101.0)])
    assert mes["aportes"] == 101.0
    assert mes["ganho"] == 10.0
    assert mes["rentabilidade_pct"] == pytest.approx(1.0)
    assert "transferencia_de_ativos" in mes["avisos"]


def test_residuo_zero_em_dados_consistentes():
    junho = _payload("2026-06-30", [_pos("B3:BBAS3", "ACAO", 100, 20.0), _selic(1.0, 15000.0), _caixa(500.0)])
    julho = _payload(
        "2026-07-31",
        [_pos("B3:BBAS3", "ACAO", 150, 22.0), _selic(1.5, 15150.0), _caixa(930.45)],
        movimentacoes=[_compra("BBAS3", "2026-07-10", 50, 1050.30)],
        proventos=[_provento("BBAS3", "2026-07-20", 10.0, q=100)],
        lotes=[{"chave_externa": SELIC, "aquisicao": "2026-07-15", "quantidade": 0.5, "valor_compra": 7530.0}],
        lancamentos=[
            ("2026-07-05", "PIX RECEBIDO", 9000.0),
            ("2026-07-12", "LIQUIDACAO BOVESPA", -1050.30),
            ("2026-07-15", "COMPRA TESOURO SELIC 2031", -7530.0),
            ("2026-07-20", "DIVIDENDOS BBAS3", 10.0),
            ("2026-07-31", "SALDO FINAL + RENDIMENTO PROVISIONADO", 1.25),
            ("2026-07-31", "IRRF S/ RENDIMENTO", -0.50),
        ],
        v_ini=17500.0,
    )
    mes = extrair_mes("2026-07-31", julho)
    assert mes["status"] == "ok"
    assert mes["ganho"] == 455.45                    # 26.955,45 − 17.500 − 9.000

    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM,
                          ganho_total=mes["ganho"], v_ini_total=mes["patrimonio_ini"])
    conc = comp["conciliacao"]
    assert conc["ativos"] == 454.70                  # 259,70 + 195,00
    assert conc["rendimento_caixa"] == 1.25
    assert conc["custos"] == -0.50
    assert conc["residuo"] == 0.0
    assert comp["avisos"] == []


def test_patrimonio_que_nao_fecha_com_as_posicoes_gera_aviso_de_residuo():
    junho, julho = _bbas3_julho()
    julho["sumario"]["atual"]["total"]["bruto"] += 100.0
    mes = extrair_mes("2026-07-31", julho)
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM,
                          ganho_total=mes["ganho"], v_ini_total=mes["patrimonio_ini"])
    assert comp["conciliacao"]["residuo"] == 100.0
    assert "residuo_alto" in comp["avisos"]


def test_sem_mes_anterior_so_mede_o_que_entrou_no_mes():
    julho = _payload(
        "2026-07-31", [_pos("B3:BBAS3", "ACAO", 150, 22.0), _pos("B3:WEGE3", "ACAO", 10, 41.0)],
        movimentacoes=[_compra("WEGE3", "2026-07-10", 10, 400.0)],
    )
    comp = composicao_mes("2026-07-31", julho, None, INI, FIM, ganho_total=50.0)
    assert _papel(comp, "B3:BBAS3")["status"] == "sem_base"
    assert _papel(comp, "B3:BBAS3")["resultado"] is None
    wege = _papel(comp, "B3:WEGE3")
    assert wege["status"] == "ok"
    assert wege["resultado"] == 10.0
    assert wege["rentabilidade_pct"] == pytest.approx(2.5)
    assert comp["conciliacao"]["residuo"] is None
    assert "sem_mes_anterior" in comp["avisos"]


def test_arquivo_v1_nao_explica_titulo_que_cresceu():
    junho = _payload("2026-06-30", [_selic(1.0, 15000.0)], versao=1)
    julho = _payload("2026-07-31", [_selic(1.5, 15150.0)], versao=1)
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)
    papel = _papel(comp, SELIC)
    assert papel["status"] == "indisponivel"
    assert papel["pendencia"] is None                # regra não resolve: reenviar o XLSX resolve
    assert "sem_lancamentos" in comp["avisos"]


def test_classe_que_entra_no_fim_do_mes_fica_sem_percentual():
    junho = _payload("2026-06-30", [_pos("B3:BBAS3", "ACAO", 100, 20.0)])
    julho = _payload(
        "2026-07-31", [_pos("B3:BBAS3", "ACAO", 100, 20.0), _pos("B3:HGLG11", "FII", 10, 101.0)],
        movimentacoes=[_compra("HGLG11", "2026-07-30", 10, 1000.0)],
    )
    comp = composicao_mes("2026-07-31", julho, junho, INI, FIM)
    fii = next(c for c in comp["classes"] if c["classe"] == "FII")
    assert fii["resultado"] == 10.0
    assert fii["rentabilidade_pct"] is None
    assert fii["aviso"] == "base_pequena"
    assert _papel(comp, "B3:HGLG11")["rentabilidade_pct"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Janela, histórico de um papel, comparação, ativo_ref
# ---------------------------------------------------------------------------

def test_acumular_encadeia_percentuais_e_soma_resultados():
    maio = _payload("2026-05-31", [_pos("B3:BBAS3", "ACAO", 100, 19.0)])
    junho, julho = _bbas3_julho()
    comps = [
        composicao_mes("2026-06-30", junho, maio, date(2026, 5, 31), INI),
        composicao_mes("2026-07-31", julho, junho, INI, FIM),
    ]
    janela = acumular(comps)
    papel = janela["ativos"][0]
    assert papel["resultado"] == 359.70
    assert papel["rentabilidade_pct"] == pytest.approx((20 / 19 * 1.105 - 1) * 100, abs=1e-3)
    assert papel["meses_com_numero"] == 2
    assert papel["status"] == "ok"
    assert papel["peso_fim_pct"] == 99.70             # 3.300 de 3.310 (com o caixa)
    assert janela["classes"][0]["resultado"] == 359.70
    assert janela["caixa"]["valor_fim"] == 10.0


def test_papel_vendido_no_meio_da_janela_fica_com_valor_zero():
    junho = _payload("2026-06-30", [_pos("B3:BBAS3", "ACAO", 100, 20.0), _pos("B3:ITSA4", "ACAO", 10, 10.0)])
    julho = _payload(
        "2026-07-31", [_pos("B3:ITSA4", "ACAO", 10, 10.0)],
        movimentacoes=[_venda("BBAS3", "2026-07-15", 100, 2100.0)],
    )
    agosto = _payload("2026-08-31", [_pos("B3:ITSA4", "ACAO", 10, 10.5)])
    comps = [
        composicao_mes("2026-07-31", julho, junho, INI, FIM),
        composicao_mes("2026-08-31", agosto, julho, FIM, date(2026, 8, 31)),
    ]
    vendido = next(a for a in acumular(comps)["ativos"] if a["chave"] == "B3:BBAS3")
    assert vendido["resultado"] == 100.0
    assert vendido["rentabilidade_pct"] == pytest.approx(5.0)
    assert vendido["valor_fim"] == 0.0
    assert vendido["peso_fim_pct"] == 0.0

    historico = historico_do_papel(comps, "B3:BBAS3")
    assert [m["mes"] for m in historico["meses"]] == ["2026-07"]
    assert historico["acumulado"]["valor_fim"] == 0.0
    assert historico_do_papel(comps, "B3:PETR4") is None


def test_comparar_dois_fechamentos():
    junho = _payload("2026-06-30", [
        _pos("B3:BBAS3", "ACAO", 100, 20.0), _pos("B3:ITSA4", "ACAO", 50, 10.0),
        _selic(1.0, 15000.0), _caixa(500.0),
    ])
    julho = _payload("2026-07-31", [
        _pos("B3:BBAS3", "ACAO", 150, 22.0), _pos("B3:WEGE3", "ACAO", 10, 41.0),
        _selic(1.0, 15100.0), _caixa(930.45),
    ])
    c = comparar(junho, julho)
    assert [x["chave"] for x in c["posicoes"]["entraram"]] == ["B3:WEGE3"]
    assert [x["chave"] for x in c["posicoes"]["sairam"]] == ["B3:ITSA4"]
    assert [x["chave"] for x in c["posicoes"]["mudaram"]] == ["B3:BBAS3"]
    assert [x["chave"] for x in c["posicoes"]["mantidos"]] == [SELIC]
    assert c["posicoes"]["mantidos"][0]["variacao"] == 100.0
    classes = {x["classe"]: x for x in c["classes"]}
    assert set(classes) == {"ACAO", "TESOURO", "CAIXA"}
    assert classes["CAIXA"]["valor_ate"] == 930.45
    assert c["total_de"] == 18000.0
    assert c["total_ate"] == 3300.0 + 410.0 + 15100.0 + 930.45


def test_ativo_ref():
    papeis = {
        "B3:BBAS3": _pos("B3:BBAS3", "ACAO", 1, 1.0),
        IPCA35: _ipca35(1.0, 1.0),
        "TD:NTNB:2035-05-15": _pos("TD:NTNB:2035-05-15", "TESOURO", 1.0, 1.0,
                                   nome="Tesouro IPCA+ com Juros Semestrais 2035"),
        SELIC: _selic(1.0, 1.0),
    }
    assert ativo_ref("ALUGUEL BBAS3 - LIQUIDO", papeis) == "B3:BBAS3"
    assert ativo_ref("JUROS TESOURO IPCA+ COM JUROS SEMESTRAIS 2035", papeis) == "TD:NTNB:2035-05-15"
    assert ativo_ref("RESGATE TESOURO SELIC 2031", papeis) == SELIC
    assert ativo_ref("RESGATE NTNB-P 2035", papeis) == IPCA35
    assert ativo_ref("RESGATE TESOURO 2035", papeis) is None         # sem nome: não atribui
    assert ativo_ref("RESGATE TESOURO SELIC 2029", papeis) is None   # ano errado
    assert ativo_ref("PIX RECEBIDO", papeis) is None


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

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
def cliente(banco):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.desempenho import router as desempenho
    from app.api.extrato_lote import router as lote

    app = FastAPI()
    app.include_router(desempenho)
    app.include_router(lote)
    return TestClient(app)


def _arquivar(engine, *payloads: dict) -> None:
    from sqlmodel import Session
    from app.models.extrato import ExtratoImportado

    with Session(engine) as s:
        for payload in payloads:
            s.add(ExtratoImportado(
                data_referencia=date.fromisoformat(payload["data_referencia"]),
                payload_json=json.dumps(payload, ensure_ascii=False),
            ))
        s.commit()


def test_rotas_de_composicao_e_de_ativo(banco, cliente):
    _arquivar(banco, *_bbas3_julho())

    corpo = cliente.get("/desempenho/composicao?janela=inicio").json()
    assert corpo["vazio"] is False
    assert corpo["janela"]["de"] == "2026-06"
    assert corpo["janela"]["sem_mes_anterior"] == ["2026-06"]
    papel = corpo["ativos"][0]
    assert papel["chave"] == "B3:BBAS3"
    assert papel["resultado"] == 259.70              # junho sem base: só julho conta
    assert papel["status"] == "parcial"

    mes = cliente.get("/desempenho/composicao?janela=mes").json()
    assert mes["meses"] == ["2026-07"]
    assert mes["ativos"][0]["status"] == "ok"
    assert mes["ativos"][0]["rentabilidade_pct"] == pytest.approx(10.5, abs=1e-4)
    assert mes["conciliacao"]["residuo"] == 0.0

    ativo = cliente.get("/desempenho/ativo", params={"chave": "B3:BBAS3"}).json()
    assert [m["mes"] for m in ativo["meses"]] == ["2026-06", "2026-07"]
    assert ativo["acumulado"]["resultado"] == 259.70
    assert cliente.get("/desempenho/ativo", params={"chave": "B3:PETR4"}).status_code == 404
    assert cliente.get("/desempenho/composicao?janela=semana").status_code == 422


def test_composicao_sem_nada_arquivado(banco, cliente):
    assert cliente.get("/desempenho/composicao").json()["vazio"] is True


def test_csv_mensal_e_por_ativo(banco, cliente):
    _arquivar(banco, *_bbas3_julho())

    resp = cliente.get("/desempenho/export.csv?tipo=mensal")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"\xef\xbb\xbf")
    linhas = resp.content.decode("utf-8-sig").splitlines()
    assert linhas[0].split(";")[:3] == ["mês", "status", "patrimônio início"]
    julho = next(l.split(";") for l in linhas if l.startswith("2026-07"))
    assert julho[1] == "ok"
    assert julho[2:5] == ["2000,00", "3310,00", "1050,30"]
    assert julho[7] == "259,70"
    assert re.fullmatch(r"\d+,\d{4}", julho[8])       # rentabilidade em pontos, vírgula decimal

    resp = cliente.get("/desempenho/export.csv?tipo=ativos")
    linhas = resp.content.decode("utf-8-sig").splitlines()
    assert linhas[0].startswith("mês;classe;ticker")
    julho = next(l.split(";") for l in linhas if l.startswith("2026-07"))
    assert julho[2] == "BBAS3"
    assert julho[5:7] == ["100", "150"]
    assert julho[14] == "259,70"
    assert julho[15] == "10,5000"


def test_comparar_meses_pela_api(banco, cliente):
    _arquivar(banco, *_bbas3_julho())

    corpo = cliente.get("/extrato/comparar?de=2026-06-30&ate=2026-07-31").json()
    assert [x["chave"] for x in corpo["posicoes"]["mudaram"]] == ["B3:BBAS3"]
    assert corpo["periodo"]["meses"] == ["2026-07"]
    assert corpo["periodo"]["considerados"] == ["2026-07"]
    assert corpo["periodo"]["proventos"] == 10.0

    assert cliente.get("/extrato/comparar?de=2026-05-31&ate=2026-07-31").status_code == 404
    assert cliente.get("/extrato/comparar?de=2026-07-31&ate=2026-06-30").status_code == 400


def test_regra_de_transferencia_entra_no_total_pela_api(banco, cliente):
    junho = _payload("2026-06-30", [_pos("B3:TAEE11", "ACAO", 100, 10.0)], v_ini=990.0)
    julho = _payload("2026-07-31", [_pos("B3:TAEE11", "ACAO", 110, 10.1)], v_ini=1000.0)
    _arquivar(banco, junho, julho)

    antes = cliente.get("/desempenho").json()["meses"][-1]
    assert antes["aportes"] == 0.0
    assert antes["ganho"] == 111.0
    pend = cliente.get("/desempenho/composicao?janela=mes").json()["pendencias"]
    assert [(p["chave"], p["data_referencia"]) for p in pend] == [("B3:TAEE11", "2026-07-31")]

    resp = cliente.post("/extrato/regras", json={
        "tipo": APORTE_EM_ATIVOS, "escopo": "ativo_mes",
        "data_referencia": "2026-07-31", "chave": "B3:TAEE11",
    })
    assert resp.status_code == 201, resp.text

    depois = cliente.get("/desempenho").json()["meses"][-1]
    assert depois["aportes"] == 101.0
    assert depois["ganho"] == 10.0
    assert "transferencia_de_ativos" in depois["avisos"]
    comp = cliente.get("/desempenho/composicao?janela=mes").json()
    assert comp["pendencias"] == []
    assert comp["ativos"][0]["status"] == "ok"
