"""
Parser v2 (docs/PLANO_HISTORICO.md, Bloco 1): razão da conta corrente, lotes de renda fixa,
movimentações de RV enriquecidas e sanitização de texto livre.

O razão é a fonte dos aportes e resgates — sem ele não dá para separar o que entrou na
carteira do que ela rendeu. A fixture sintética padrão só tem créditos de proventos;
débitos, transferências, compras e lotes novos vêm dos helpers de tests/planilhas.py.
"""
import json
import re
from datetime import date

import pytest

from app.tools.btg_xlsx_parser import (
    VERSAO_PARSER,
    mascarar_nome_arquivo,
    parse_btg_xlsx,
    sanitizar_descricao,
)
from tests.gerador_extrato import (
    CAIXA_FIM_FIXTURE,
    CAIXA_INI_FIXTURE,
    CREDITOS_FIXTURE,
    DATA_REFERENCIA_FIXTURE,
    LFT31_AQUISICAO_FIXTURE,
    LFT31_PRECO_ATUAL_FIXTURE,
    LFT31_PRECO_COMPRA_FIXTURE,
    LFT31_TAXA_FIXTURE,
    LFT31_VALOR_COMPRA_FIXTURE,
    LOTES_RF_FIXTURE,
    NTNB_CUSTO_TOTAL_FIXTURE,
    NTNB_LOTES_FIXTURE,
    RENDIMENTO_KNCR11_FIXTURE,
    TOTAL_POSICOES_VALOR_FIXTURE,
    VALORES_RAZAO_FIXTURE,
)
from tests.planilhas import (
    abrir_fixture,
    adicionar_lancamentos,
    adicionar_lote_rf,
    adicionar_movimentacao_rv,
    bytes_fixture,
    para_bytes,
)

RE_CPF = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")


@pytest.fixture(scope="module")
def extrato():
    return parse_btg_xlsx(bytes_fixture())


# ---------------------------------------------------------------------------
# Fixture sintética padrão
# ---------------------------------------------------------------------------

def test_razao_da_conta_da_fixture(extrato):
    """5 lançamentos (JCP, 3 rendimentos de FII, rendimento do saldo); o razão fecha."""
    assert extrato.versao_parser == VERSAO_PARSER >= 2
    assert extrato.saldo_inicial_conta == pytest.approx(CAIXA_INI_FIXTURE)

    lanc = extrato.lancamentos_conta
    assert [l["seq"] for l in lanc] == [0, 1, 2, 3, 4]
    assert [l["valor"] for l in lanc] == pytest.approx(VALORES_RAZAO_FIXTURE)
    assert lanc[0]["data"] == "2026-07-01"
    assert lanc[-1]["data"] == DATA_REFERENCIA_FIXTURE
    assert lanc[-1]["descricao"].startswith("Saldo Final")
    # ticker preservado: é por ele que o provento casa com o papel
    assert lanc[1]["descricao"].endswith("KNCR11")

    conta = extrato.checagem["conta_corrente"]
    assert conta["ok"] is True
    assert conta["diferenca"] == pytest.approx(0.0)
    assert conta["creditos"] == pytest.approx(CREDITOS_FIXTURE)
    assert conta["creditos_extrato"] == pytest.approx(CREDITOS_FIXTURE)
    assert conta["debitos"] == pytest.approx(0.0)
    assert conta["vs_caixa"] == pytest.approx(0.0)
    assert conta["vs_sumario_anterior"] == pytest.approx(0.0)


def test_checagem_das_posicoes_continua_a_mesma(extrato):
    """O `ok` de cima ainda é posições × Sumário — o razão tem chave própria."""
    assert extrato.checagem["ok"] is True
    assert extrato.checagem["total_parseado"] == pytest.approx(TOTAL_POSICOES_VALOR_FIXTURE, abs=0.01)


def test_lotes_de_renda_fixa(extrato):
    """8 lotes, com data de aquisição, e chave igual à da posição do papel."""
    lotes = extrato.lotes_rf
    assert len(lotes) == LOTES_RF_FIXTURE
    chaves_posicoes = {p.chave_externa for p in extrato.posicoes}
    assert {l["chave_externa"] for l in lotes} <= chaves_posicoes

    lft31 = next(l for l in lotes if l["chave_externa"] == "TD:LFT:2031-03-01")
    assert lft31["aquisicao"] == LFT31_AQUISICAO_FIXTURE
    assert lft31["valor_compra"] == pytest.approx(LFT31_VALOR_COMPRA_FIXTURE)
    assert lft31["preco_compra"] == pytest.approx(LFT31_PRECO_COMPRA_FIXTURE)
    assert lft31["preco_atual"] == pytest.approx(LFT31_PRECO_ATUAL_FIXTURE), \
        "pegou o preço de compra no lugar do atual"
    assert lft31["taxa_compra"] == LFT31_TAXA_FIXTURE

    ipca = [l for l in lotes if l["chave_externa"] == "TD:NTNB-P:2029-05-15"]
    assert len(ipca) == NTNB_LOTES_FIXTURE
    assert sum(l["valor_compra"] for l in ipca) == pytest.approx(NTNB_CUSTO_TOTAL_FIXTURE, abs=0.01)


def test_movimentacao_rv_ganha_classe_e_operacao(extrato):
    por_ticker = {p["ticker"]: p for p in extrato.proventos}
    assert por_ticker["ITUB4"]["classe"] == "ACAO"
    assert por_ticker["KNCR11"]["classe"] == "FII"
    assert all(p["operacao"] == "PROVENTO" for p in extrato.proventos)
    assert extrato.checagem["movimentacao_rv"]["ok"] is True


def test_payload_arquivado_tem_os_campos_novos(extrato):
    d = extrato.to_dict()
    for campo in ("versao_parser", "saldo_inicial_conta", "lancamentos_conta", "lotes_rf"):
        assert campo in d
    json.dumps(d, ensure_ascii=False)   # o arquivamento serializa o dicionário inteiro


# ---------------------------------------------------------------------------
# Extratos sintéticos
# ---------------------------------------------------------------------------

def _extrato_com_transferencias(debitos_positivos: bool):
    wb = abrir_fixture()
    adicionar_lancamentos(wb, [
        (date(2026, 7, 16), "PIX RECEBIDO - FULANO DE TAL CPF 123.456.789-00", 2000.00),
        (date(2026, 7, 20), "TED ENVIADA BCO 341 AG 0001 CC 12345-6 FULANO DE TAL", -500.00),
    ], debitos_positivos=debitos_positivos)
    return parse_btg_xlsx(para_bytes(wb))


@pytest.mark.parametrize("debitos_positivos", [False, True])
def test_aporte_e_resgate_com_sinal_certo(debitos_positivos):
    """O sinal vem do saldo: o débito sai negativo mesmo escrito sem sinal na coluna."""
    extrato = _extrato_com_transferencias(debitos_positivos)
    por_valor = {l["valor"]: l for l in extrato.lancamentos_conta}
    assert 2000.0 in por_valor and -500.0 in por_valor

    conta = extrato.checagem["conta_corrente"]
    assert conta["ok"] is True, conta
    assert conta["debitos"] == pytest.approx(-500.0)
    caixa = next(p for p in extrato.posicoes if p.classe == "CAIXA")
    assert caixa.valor_mercado == pytest.approx(CAIXA_FIM_FIXTURE + 1500.0)
    assert extrato.checagem["ok"] is True, "o extrato sintético tem de continuar coerente"


def test_transferencias_saem_sem_nome_cpf_ou_conta():
    extrato = _extrato_com_transferencias(debitos_positivos=False)
    por_valor = {l["valor"]: l["descricao"] for l in extrato.lancamentos_conta}
    assert por_valor[2000.0] == "PIX RECEBIDO"
    assert por_valor[-500.0] == "TED ENVIADA"

    texto = json.dumps(extrato.to_dict(), ensure_ascii=False)
    assert "FULANO" not in texto
    assert not RE_CPF.search(texto)
    assert "12345-6" not in texto


def test_razao_que_nao_fecha_vira_aviso():
    """Uma linha lida errado pode ser um aporte: o razão que não fecha é sinalizado."""
    wb = abrir_fixture()
    ws = wb["Conta Corrente"]
    for row in ws.iter_rows():
        for c in row:
            if c.value == RENDIMENTO_KNCR11_FIXTURE:
                c.value = RENDIMENTO_KNCR11_FIXTURE + 5.1   # valor muda, saldo não: a linha não confere
    extrato = parse_btg_xlsx(para_bytes(wb))
    conta = extrato.checagem["conta_corrente"]
    assert conta["ok"] is False
    assert conta["sinal_divergente"] == 1
    assert "provisória" in conta["aviso"]


def test_compra_de_acao_na_movimentacao():
    wb = abrir_fixture()
    adicionar_movimentacao_rv(wb, "Ações", [{
        "data": date(2026, 7, 10), "transacao": "COMPRA", "codigo": "BBAS3", "qtde": 50,
        "preco": 21.0, "valor_bruto": 1050.0, "corretagem": 0.30, "valor_liquido": 1050.30,
    }])
    extrato = parse_btg_xlsx(para_bytes(wb))

    compra = next(m for m in extrato.movimentacoes if m["ticker"] == "BBAS3")
    assert compra["operacao"] == "COMPRA"
    assert compra["classe"] == "ACAO"
    assert compra["data"] == "2026-07-10"
    assert compra["preco"] == pytest.approx(21.0)
    assert compra["corretagem"] == pytest.approx(0.30)
    assert compra["valor_liquido"] == pytest.approx(1050.30)
    assert extrato.checagem["movimentacao_rv"]["ok"] is True
    assert len(extrato.proventos) == 4, "a compra não pode virar provento"


def test_lote_novo_de_tesouro():
    """Compra de Tesouro no mês = lote com aquisição dentro do período."""
    wb = abrir_fixture()
    adicionar_lote_rf(wb, "LFT", {
        "ativo": "LFT", "emissao": date(2025, 1, 8), "vencimento": date(2031, 3, 1),
        "aquisicao": date(2026, 7, 20), "taxa_compra": "SELIC + 0,09%", "quantidade": 0.05,
        "preco_compra": 18900.00, "valor_compra": 945.00,
        "preco": LFT31_PRECO_ATUAL_FIXTURE, "saldo_bruto": round(0.05 * LFT31_PRECO_ATUAL_FIXTURE, 2),
    })
    extrato = parse_btg_xlsx(para_bytes(wb))
    novos = [l for l in extrato.lotes_rf if l["aquisicao"] == "2026-07-20"]
    assert len(novos) == 1
    assert novos[0]["chave_externa"] == "TD:LFT:2031-03-01"
    assert novos[0]["valor_compra"] == pytest.approx(945.0)
    assert len(extrato.lotes_rf) == LOTES_RF_FIXTURE + 1


# ---------------------------------------------------------------------------
# Sanitização
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto, valor, esperado", [
    ("PIX RECEBIDO - FULANO DE TAL CPF 123.456.789-00", 100.0, "PIX RECEBIDO"),
    ("PIX FULANO DA SILVA", -100.0, "PIX ENVIADO"),
    ("TED ENVIADA BCO 341 AG 0001 CC 12345-6 FULANO", -100.0, "TED ENVIADA"),
    ("TRANSFERENCIA ENTRE CONTAS 00012345678", 100.0, "TRANSFERENCIA ENTRE CONTAS RECEBIDO"),
    ("PIX ***.456.789-** MARIA", 100.0, "PIX RECEBIDO"),
])
def test_transferencia_fica_so_com_o_vocabulario(texto, valor, esperado):
    assert sanitizar_descricao(texto, valor) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("JUROS S/ CAPITAL - À VISTA s/ ITAUUNIBANCOPN N1 - ITUB4",
     "JUROS S/ CAPITAL - À VISTA s/ ITAUUNIBANCOPN N1 - ITUB4"),
    ("RESGATE TESOURO DIRETO NTNB 15/05/2029", "RESGATE TESOURO DIRETO NTNB 15/05/2029"),
    ("IRRF S/ RESGATE 123456789", "IRRF S/ RESGATE ***"),
    ("DEVOLUCAO 12.345.678/0001-90", "DEVOLUCAO ***"),
])
def test_outras_linhas_mascaram_so_os_numeros_de_documento(texto, esperado):
    assert sanitizar_descricao(texto, 1.0) == esperado


def test_nome_do_arquivo_sem_numero_da_conta():
    assert mascarar_nome_arquivo("001234567.xlsx") == "***.xlsx"
    assert mascarar_nome_arquivo("extrato_001234567_jul.xlsx") == "extrato_***_jul.xlsx"
    assert mascarar_nome_arquivo("extrato_exemplo.xlsx") == "extrato_exemplo.xlsx"
    assert mascarar_nome_arquivo(None) is None


def test_upload_mascara_o_nome_antes_do_staging():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.extrato import router
    from app.tools import extrato_staging

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        resp = client.post("/extrato/upload", files={"arquivo": ("001234567.xlsx", bytes_fixture())})
        assert resp.status_code == 200, resp.text
        assert resp.json()["arquivo"] == "***.xlsx"
        assert extrato_staging.get()["arquivo"] == "***.xlsx"
        # o preview que vai ao modelo continua só com a conferência das posições
        assert "conta_corrente" not in resp.json()["checagem_totais"]
    finally:
        extrato_staging.clear()
