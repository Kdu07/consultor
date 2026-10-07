"""
Validador de invariantes (app/tools/extrato_validacao.py) — contrato congelado.

A maior parte dos testes trabalha sobre um payload v3 montado à mão (validar_extrato é
puro); o fim-a-fim usa o XLSX sintético de test_parser_correcoes. Cada família V1–V10 é
exercitada nas três severidades da régua (ok ≤ 0,05 < aviso ≤ 1,00 < erro) ou no seu
modo estrutural. VALORES INVENTADOS — nada da carteira real em arquivo versionado.
"""
import json
from datetime import date

import pytest

from app.tools.btg_xlsx_parser import parse_btg_xlsx
from app.tools.extrato_validacao import (
    TOLERANCIA_ERRO,
    TOLERANCIA_OK,
    anexar_validacao,
    validar_encadeamento,
    validar_extrato,
)
from tests.test_parser_correcoes import xlsx_completo

# Mesmo universo sintético do XLSX de test_parser_correcoes (fechando ao centavo).
RV = 2851.5          # 2550 (Ações) + 300 (ETF) + 1,50 (resultado do aluguel)
RF_B, RF_L = 24000.0, 23900.0
FUNDO_B, FUNDO_L = 1050.0, 1040.0
CRIPTO = 5000.0
CAIXA = 500.0
TRANSITO = 30.0
TOTAL_B = RV + RF_B + FUNDO_B + CRIPTO + CAIXA + TRANSITO
TOTAL_L = RV + RF_L + FUNDO_L + CRIPTO + CAIXA + TRANSITO
ANT_B, ANT_L = 32600.0, 32485.0


def payload_v3() -> dict:
    """Payload mínimo e coerente: todos os checks saem 'ok'."""
    return {
        "versao_parser": 3,
        "data_referencia": "2026-06-30",
        "sumario": {
            "atual": {
                "data": "2026-06-30",
                "mercados": {
                    "Renda Variável": {"bruto": RV, "liquido": RV},
                    "Renda Fixa": {"bruto": RF_B, "liquido": RF_L},
                    "Fundos de Investimento": {"bruto": FUNDO_B, "liquido": FUNDO_L},
                    "CriptoAtivos": {"bruto": CRIPTO, "liquido": CRIPTO},
                    "Conta Corrente": {"bruto": CAIXA, "liquido": CAIXA},
                    "Valores em Trânsito": {"bruto": TRANSITO, "liquido": TRANSITO},
                },
                "total": {"bruto": TOTAL_B, "liquido": TOTAL_L},
            },
            "anterior": {
                "data": "2026-05-31",
                "mercados": {
                    "Renda Variável": {"bruto": 2800.0, "liquido": 2790.0},
                    "Renda Fixa": {"bruto": 23800.0, "liquido": 23700.0},
                    "Fundos de Investimento": {"bruto": 1000.0, "liquido": 995.0},
                    "CriptoAtivos": {"bruto": 4900.0, "liquido": 4900.0},
                    "Conta Corrente": {"bruto": 100.0, "liquido": 100.0},
                    "Valores em Trânsito": {"bruto": 0.0, "liquido": 0.0},
                },
                "total": {"bruto": ANT_B, "liquido": ANT_L},
            },
            "meta": {"periodo_inicio": "2026-06-01", "emitido_em": "2026-07-01"},
        },
        "posicoes": [
            {"chave_externa": "B3:BBAS3", "ticker": "BBAS3", "classe": "ACAO",
             "quantidade": 100.0, "preco_fechamento": 25.5, "valor_mercado": 2550.0},
            {"chave_externa": "B3:IVVB11", "ticker": "IVVB11", "classe": "ETF",
             "quantidade": 10.0, "preco_fechamento": 30.0, "valor_mercado": 300.0},
            {"chave_externa": "TD:LFT:2031-03-01", "classe": "TESOURO",
             "quantidade": 1.5, "preco_fechamento": 16000.0, "valor_mercado": RF_B},
            {"chave_externa": "FUNDO:11-222-333-0001-44", "classe": "FUNDO",
             "quantidade": 10.0, "preco_fechamento": 105.0, "valor_mercado": FUNDO_B},
            {"chave_externa": "CRIPTO:XBT", "ticker": "XBT", "classe": "CRIPTO",
             "quantidade": 0.01, "preco_fechamento": 500000.0, "valor_mercado": CRIPTO},
            {"chave_externa": "CAIXA:BTG", "classe": "CAIXA", "quantidade": 1.0,
             "preco_fechamento": None, "valor_mercado": CAIXA, "as_of": "2026-06-30"},
        ],
        "aluguel": [{"ticker": "TAEE11", "resultado_acumulado_liquido": 1.5}],
        "valores_em_transito": [{"valor": TRANSITO}],
        "totais_abas": {
            "renda_variavel": [
                {"bloco": "Posição > Ações", "rotulo": "Total em Ações R$",
                 "valores": {"saldo bruto r$": 2550.0},
                 "soma_linhas": {"saldo bruto r$": 2550.0}},
                {"bloco": "Posição > ETF", "rotulo": "Total em ETF's R$",
                 "valores": {"saldo bruto r$": 300.0},
                 "soma_linhas": {"saldo bruto r$": 300.0}},
                {"bloco": "Posição > Ações | Aluguel", "rotulo": "Total em Aluguel de Ações R$",
                 "valores": {"valor contratado r$": 350.0, "result. acum. liq. r$": 1.5},
                 "soma_linhas": {"valor contratado r$": 350.0}},
            ],
            "renda_fixa": [
                {"bloco": "Posição > TESOURO DIRETO - LFT", "rotulo": "Total",
                 "valores": {"saldo bruto r$": RF_B, "saldo liquido r$": RF_L},
                 "soma_linhas": {"saldo bruto r$": RF_B, "saldo liquido r$": RF_L}},
            ],
            "fundos": [
                {"bloco": "Posição > Portfólio de fundos", "rotulo": "Total em fundos",
                 "valores": {"saldo bruto r$": FUNDO_B, "saldo liquido r$": FUNDO_L},
                 "soma_linhas": {"saldo bruto r$": FUNDO_B}},
            ],
            "cripto": [
                {"bloco": "Posição > Portfólio de CriptoAtivos", "rotulo": "Total",
                 "valores": {"valor bruto r$": CRIPTO},
                 "soma_linhas": {"valor bruto r$": CRIPTO}},
            ],
            "valores_em_transito": [
                {"bloco": "Renda Variavel", "rotulo": "Total",
                 "valores": {"valor r$": TRANSITO}, "soma_linhas": {"valor r$": TRANSITO}},
            ],
        },
        "checagem": {
            "ok": True,
            "conta_corrente": {
                "encontrada": True, "ok": True,
                "saldo_inicial": 100.0, "soma_lancamentos": 400.0, "saldo_final": 500.0,
                "creditos": 400.0, "creditos_extrato": 400.0,
                "debitos": 0.0, "debitos_extrato": 0.0,
                "diferenca": 0.0, "dif_creditos": 0.0, "dif_debitos": 0.0,
                "vs_caixa": 0.0, "vs_sumario_anterior": 0.0,
                "linhas_descartadas": 0, "sinal_divergente": 0,
            },
        },
        "avisos_parser": [],
        "lancamentos_conta": [],
    }


def _check(resultado: dict, cid: str) -> dict:
    achados = [c for c in resultado["checks"] if c["id"] == cid]
    assert achados, f"check {cid} ausente — ids: {[c['id'] for c in resultado['checks']]}"
    return achados[0]


def _ids(resultado: dict) -> set:
    return {c["id"] for c in resultado["checks"]}


# ---------------------------------------------------------------------------
# Contrato e veredito
# ---------------------------------------------------------------------------

def test_payload_coerente_sai_ok_e_contrato_estavel():
    r = validar_extrato(payload_v3())
    assert r["versao_validador"] == 1
    assert r["veredito"] == "ok"
    assert r["erros"] == [] and r["avisos"] == []
    assert r["tolerancias"] == {"ok": TOLERANCIA_OK, "erro": TOLERANCIA_ERRO}
    for c in r["checks"]:
        assert set(c) == {"id", "rotulo", "severidade", "esperado", "obtido", "diferenca", "detalhe"}
        assert c["severidade"] in ("ok", "aviso", "erro", "nao_avaliavel")


def test_veredito_agregado_erro_vence_aviso():
    p = payload_v3()
    p["sumario"]["atual"]["total"]["bruto"] += 0.5           # V1 aviso
    p["totais_abas"]["renda_fixa"][0]["soma_linhas"]["saldo bruto r$"] -= 50.0  # V3 seção erro
    r = validar_extrato(p)
    assert r["veredito"] == "erro"
    assert r["erros"] and r["avisos"]


@pytest.mark.parametrize("payload", [{}, {"versao_parser": 2, "sumario": {"atual": {}}}])
def test_payload_v1_v2_sai_nao_avaliavel_com_nota(payload):
    r = validar_extrato(payload)
    assert r["veredito"] == "ok"
    assert r["checks"] and all(c["severidade"] == "nao_avaliavel" for c in r["checks"])
    assert any("anterior ao validador" in a for a in r["avisos"])


# ---------------------------------------------------------------------------
# V1 — Sumário
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta, severidade", [(0.03, "ok"), (0.5, "aviso"), (5.0, "erro")])
def test_v1_tres_severidades(delta, severidade):
    p = payload_v3()
    p["sumario"]["atual"]["total"]["bruto"] += delta
    c = _check(validar_extrato(p), "V1_SUMARIO_BRUTO_FIM")
    assert c["severidade"] == severidade
    assert c["diferenca"] == pytest.approx(-delta)


def test_v1_sem_periodo_anterior_fica_nao_avaliavel():
    p = payload_v3()
    del p["sumario"]["anterior"]
    r = validar_extrato(p)
    assert _check(r, "V1_SUMARIO_BRUTO_INI")["severidade"] == "nao_avaliavel"
    assert _check(r, "V1_SUMARIO_LIQ_INI")["severidade"] == "nao_avaliavel"
    assert _check(r, "V1_SUMARIO_BRUTO_FIM")["severidade"] == "ok"


# ---------------------------------------------------------------------------
# V2 — RV com aluguel
# ---------------------------------------------------------------------------

def test_v2_aluguel_fecha_a_conta():
    # Sem o resultado do aluguel a conta ERRA por 1,50 — era o falso alarme permanente.
    p = payload_v3()
    assert _check(validar_extrato(p), "V2_RV_TOTAL")["severidade"] == "ok"
    p["aluguel"] = []
    c = _check(validar_extrato(p), "V2_RV_TOTAL")
    assert c["severidade"] == "erro"
    assert c["diferenca"] == pytest.approx(-1.5)


def test_v2_aviso_em_divergencia_pequena():
    p = payload_v3()
    p["aluguel"][0]["resultado_acumulado_liquido"] = 1.0      # dif -0,50
    assert _check(validar_extrato(p), "V2_RV_TOTAL")["severidade"] == "aviso"


def test_v2_sem_rv_fica_nao_avaliavel():
    p = payload_v3()
    p["totais_abas"]["renda_variavel"] = []
    del p["sumario"]["atual"]["mercados"]["Renda Variável"]
    assert _check(validar_extrato(p), "V2_RV_TOTAL")["severidade"] == "nao_avaliavel"


# ---------------------------------------------------------------------------
# V3 — RF por seção + colisão sem vencimento
# ---------------------------------------------------------------------------

def test_v3_total_bruto_e_liquido_contra_sumario():
    p = payload_v3()
    r = validar_extrato(p)
    assert _check(r, "V3_RF_TOTAL_BRUTO")["severidade"] == "ok"
    assert _check(r, "V3_RF_TOTAL_LIQ")["severidade"] == "ok"
    p["sumario"]["atual"]["mercados"]["Renda Fixa"]["liquido"] += 0.2
    assert _check(validar_extrato(p), "V3_RF_TOTAL_LIQ")["severidade"] == "aviso"


def test_v3_secao_pega_linha_perdida_dentro_do_bloco():
    p = payload_v3()
    p["totais_abas"]["renda_fixa"][0]["soma_linhas"]["saldo bruto r$"] = RF_B - 1000.0
    c = _check(validar_extrato(p), "V3_RF_SECAO_TESOURO-DIRETO-LFT")
    assert c["severidade"] == "erro"
    assert c["diferenca"] == pytest.approx(-1000.0)


def test_v3_colisao_sem_vencimento_e_erro_estrutural():
    p = payload_v3()
    p["avisos_parser"].append({
        "tipo": "colisao_sem_vencimento", "aba": "Renda Fixa",
        "detalhe": "TD:LFT:sem-vencimento: mais de um papel agregado sem vencimento legível",
    })
    r = validar_extrato(p)
    c = _check(r, "V3_RF_COLISAO_VENCIMENTO")
    assert c["severidade"] == "erro"
    assert r["veredito"] == "erro"


# ---------------------------------------------------------------------------
# V4 — conta corrente (REUSA as diferenças de checagem.conta_corrente)
# ---------------------------------------------------------------------------

def test_v4_razao_usa_diferenca_ja_computada():
    p = payload_v3()
    p["checagem"]["conta_corrente"]["diferenca"] = 0.14       # salto visto em extrato real
    assert _check(validar_extrato(p), "V4_CC_RAZAO")["severidade"] == "aviso"
    p["checagem"]["conta_corrente"]["diferenca"] = 2.0
    assert _check(validar_extrato(p), "V4_CC_RAZAO")["severidade"] == "erro"


def test_v4_netting_do_btg_vira_aviso_nao_erro():
    # Créditos e débitos divergindo pelo MESMO valor com razão fechando = liquidação
    # nettada numa linha e contada pelo bruto nos totais (inconsistência do próprio BTG).
    p = payload_v3()
    cc = p["checagem"]["conta_corrente"]
    cc["dif_creditos"] = cc["dif_debitos"] = -2.5
    r = validar_extrato(p)
    assert _check(r, "V4_CC_CREDITOS")["severidade"] == "aviso"
    assert _check(r, "V4_CC_DEBITOS")["severidade"] == "aviso"
    assert r["veredito"] == "aviso"


def test_v4_divergencia_so_de_um_lado_continua_erro():
    p = payload_v3()
    p["checagem"]["conta_corrente"]["dif_creditos"] = -2.5    # débito fecha: linha sumiu?
    r = validar_extrato(p)
    assert _check(r, "V4_CC_CREDITOS")["severidade"] == "erro"
    assert r["veredito"] == "erro"


def test_v4_saldo_anterior_divergindo_centavos_e_ok():
    p = payload_v3()
    p["checagem"]["conta_corrente"]["vs_sumario_anterior"] = -0.05
    assert _check(validar_extrato(p), "V4_CC_VS_SUMARIO_ANTERIOR")["severidade"] == "ok"


def test_v4_sem_razao_fica_nao_avaliavel():
    p = payload_v3()
    p["checagem"]["conta_corrente"] = {"encontrada": False}
    r = validar_extrato(p)
    for cid in ("V4_CC_RAZAO", "V4_CC_CREDITOS", "V4_CC_DEBITOS",
                "V4_CC_VS_CAIXA", "V4_CC_VS_SUMARIO_ANTERIOR"):
        assert _check(r, cid)["severidade"] == "nao_avaliavel"


# ---------------------------------------------------------------------------
# V5 — trânsito | V6 — fundos e cripto
# ---------------------------------------------------------------------------

def test_v5_linhas_vs_total_vs_sumario():
    p = payload_v3()
    r = validar_extrato(p)
    assert _check(r, "V5_TRANSITO_TOTAL")["severidade"] == "ok"
    assert _check(r, "V5_TRANSITO_SUMARIO")["severidade"] == "ok"
    p["valores_em_transito"] = [{"valor": TRANSITO - 0.5}]
    assert _check(validar_extrato(p), "V5_TRANSITO_TOTAL")["severidade"] == "aviso"
    p["sumario"]["atual"]["mercados"]["Valores em Trânsito"]["bruto"] = TRANSITO + 5
    assert _check(validar_extrato(p), "V5_TRANSITO_SUMARIO")["severidade"] == "erro"


@pytest.mark.parametrize("delta, severidade", [(0.0, "ok"), (0.5, "aviso"), (5.0, "erro")])
def test_v6_fundos_tres_severidades(delta, severidade):
    p = payload_v3()
    p["sumario"]["atual"]["mercados"]["Fundos de Investimento"]["bruto"] = FUNDO_B + delta
    assert _check(validar_extrato(p), "V6_FUNDOS")["severidade"] == severidade


def test_v6_cripto_aba_so_de_movimentacao_compara_zero():
    # Posição vendida no período: aba sem bloco de posição e mercado '-' no Sumário.
    p = payload_v3()
    p["totais_abas"]["cripto"] = []
    p["posicoes"] = [q for q in p["posicoes"] if q["classe"] != "CRIPTO"]
    p["sumario"]["atual"]["mercados"]["CriptoAtivos"] = {"bruto": None, "liquido": None}
    p["sumario"]["atual"]["total"]["bruto"] = TOTAL_B - CRIPTO
    p["sumario"]["atual"]["total"]["liquido"] = TOTAL_L - CRIPTO
    r = validar_extrato(p)
    assert _check(r, "V6_CRIPTO")["severidade"] == "ok"
    assert _check(r, "V8_COBERTURA_CRIPTOATIVOS")["severidade"] == "ok"


def test_v6_ausente_quando_extrato_nao_tem_a_classe():
    p = payload_v3()
    p["totais_abas"]["fundos"] = []
    p["posicoes"] = [q for q in p["posicoes"] if q["classe"] != "FUNDO"]
    del p["sumario"]["atual"]["mercados"]["Fundos de Investimento"]
    p["sumario"]["atual"]["total"]["bruto"] = TOTAL_B - FUNDO_B
    p["sumario"]["atual"]["total"]["liquido"] = TOTAL_L - FUNDO_L
    assert "V6_FUNDOS" not in _ids(validar_extrato(p))


# ---------------------------------------------------------------------------
# V7 — encadeamento (precisa de banco)
# ---------------------------------------------------------------------------

def _sessao_com_mes_anterior(data_ref=date(2026, 5, 31), total_bruto=ANT_B,
                             total_liq=ANT_L, data_sumario="2026-05-31"):
    from sqlmodel import Session, SQLModel, create_engine

    from app.models.extrato import ExtratoImportado

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(ExtratoImportado(
        data_referencia=data_ref,
        payload_json=json.dumps({
            "versao_parser": 3,
            "sumario": {"atual": {"data": data_sumario,
                                  "total": {"bruto": total_bruto, "liquido": total_liq}}},
        }),
    ))
    session.commit()
    return session


def test_v7_encadeia_com_mes_arquivado_anterior():
    session = _sessao_com_mes_anterior()
    checks = {c["id"]: c for c in validar_encadeamento(session, payload_v3())}
    assert checks["V7_ENCADEAMENTO_BRUTO"]["severidade"] == "ok"
    assert checks["V7_ENCADEAMENTO_LIQ"]["severidade"] == "ok"


def test_v7_divergencia_grande_vira_no_maximo_aviso():
    session = _sessao_com_mes_anterior(total_bruto=ANT_B - 100.0)
    checks = {c["id"]: c for c in validar_encadeamento(session, payload_v3())}
    c = checks["V7_ENCADEAMENTO_BRUTO"]
    assert c["severidade"] == "aviso"            # nunca erro, por contrato
    assert c["diferenca"] == pytest.approx(100.0)


def test_v7_meses_nao_contiguos_ficam_nao_avaliavel():
    session = _sessao_com_mes_anterior(data_ref=date(2026, 4, 30), data_sumario="2026-04-30")
    checks = validar_encadeamento(session, payload_v3())
    assert all(c["severidade"] == "nao_avaliavel" for c in checks)
    assert any("contíguos" in c["detalhe"] for c in checks)


def test_v7_sem_mes_anterior_fica_nao_avaliavel():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        checks = validar_encadeamento(session, payload_v3())
    assert all(c["severidade"] == "nao_avaliavel" for c in checks)


# ---------------------------------------------------------------------------
# V8 — cobertura | V9 — datas
# ---------------------------------------------------------------------------

def test_v8_mercado_com_saldo_sem_posicoes_e_erro():
    p = payload_v3()
    p["posicoes"] = [q for q in p["posicoes"] if q["classe"] not in ("ACAO", "ETF")]
    r = validar_extrato(p)
    c = _check(r, "V8_COBERTURA_RENDA-VARIAVEL")
    assert c["severidade"] == "erro"
    assert r["veredito"] == "erro"


def test_v8_mercado_desconhecido_e_erro():
    p = payload_v3()
    p["sumario"]["atual"]["mercados"]["Derivativos"] = {"bruto": 10.0, "liquido": 10.0}
    c = _check(validar_extrato(p), "V8_COBERTURA_DERIVATIVOS")
    assert c["severidade"] == "erro"
    assert "desconhecido" in c["detalhe"]


def test_v8_mercado_zerado_sem_posicoes_e_ok():
    p = payload_v3()
    p["posicoes"] = [q for q in p["posicoes"] if q["classe"] != "FUNDO"]
    p["totais_abas"]["fundos"] = []
    p["sumario"]["atual"]["mercados"]["Fundos de Investimento"] = {"bruto": None, "liquido": None}
    p["sumario"]["atual"]["total"]["bruto"] = TOTAL_B - FUNDO_B
    p["sumario"]["atual"]["total"]["liquido"] = TOTAL_L - FUNDO_L
    c = _check(validar_extrato(p), "V8_COBERTURA_FUNDOS-DE-INVESTIMENTO")
    assert c["severidade"] == "ok" and "zerado" in c["detalhe"]


def test_v9_datas_alinhadas_ok_desalinhadas_aviso():
    p = payload_v3()
    assert _check(validar_extrato(p), "V9_DATAS")["severidade"] == "ok"
    p["posicoes"][-1]["as_of"] = "2026-06-29"       # CAIXA com data diferente do fim
    c = _check(validar_extrato(p), "V9_DATAS")
    assert c["severidade"] == "aviso" and "CAIXA" in c["detalhe"]
    p = payload_v3()
    p["sumario"]["meta"]["emitido_em"] = "2026-06-15"
    assert _check(validar_extrato(p), "V9_DATAS")["severidade"] == "aviso"


# ---------------------------------------------------------------------------
# V10 — quantidade × preço
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("preco, severidade", [
    (25.50, "ok"),         # 100 × 25,50 = 2550
    (25.51, "aviso"),      # dif 1,00
    (26.00, "erro"),       # dif 50,00
])
def test_v10_tres_severidades(preco, severidade):
    p = payload_v3()
    p["posicoes"][0]["preco_fechamento"] = preco
    assert _check(validar_extrato(p), "V10_QTDE_PRECO")["severidade"] == severidade


def test_v10_vira_nota_informativa_em_extrato_decorado():
    # Período aberto: preço de fechamento de datas distintas por posição — não fecha
    # mesmo com parse certo, então nunca passa de aviso.
    p = payload_v3()
    p["posicoes"][0]["preco_fechamento"] = 26.00
    p["avisos_parser"].append({"tipo": "ticker_decorado", "aba": "Renda Variavel",
                               "detalhe": "BBAS3: código veio decorado ('*')"})
    c = _check(validar_extrato(p), "V10_QTDE_PRECO")
    assert c["severidade"] == "aviso"
    assert "decorado" in c["detalhe"]


def test_v10_quantidade_zero_em_classe_com_cotacao_e_erro_estrutural():
    p = payload_v3()
    p["posicoes"][0]["quantidade"] = 0.0            # ACAO com valor e quantidade 0
    r = validar_extrato(p)
    c = _check(r, "V10_QTDE_ZERO")
    assert c["severidade"] == "erro"
    assert "B3:BBAS3" in c["detalhe"]
    assert r["veredito"] == "erro"


# ---------------------------------------------------------------------------
# anexar_validacao — fim a fim com o XLSX sintético
# ---------------------------------------------------------------------------

def test_anexar_validacao_poe_validacao_irma_de_checagem():
    extrato = parse_btg_xlsx(xlsx_completo())
    payload = anexar_validacao(extrato)
    assert payload["validacao"]["veredito"] == "ok"
    assert "validacao" not in payload["checagem"]   # irmã, nunca dentro (preview filtra)
    assert "V7_ENCADEAMENTO_BRUTO" not in {c["id"] for c in payload["validacao"]["checks"]}


def test_anexar_validacao_com_session_inclui_v7():
    extrato = parse_btg_xlsx(xlsx_completo())
    session = _sessao_com_mes_anterior()
    payload = anexar_validacao(extrato, session)
    checks = {c["id"]: c for c in payload["validacao"]["checks"]}
    assert checks["V7_ENCADEAMENTO_BRUTO"]["severidade"] == "ok"
    assert checks["V7_ENCADEAMENTO_LIQ"]["severidade"] == "ok"
    assert payload["validacao"]["veredito"] == "ok"
