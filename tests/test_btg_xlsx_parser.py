"""
Parser do extrato XLSX do BTG (docs/PLANO_XLSX.md, Bloco 1).

A fixture é 100% SINTÉTICA (tests/gerador_extrato.py): mesma forma do extrato real —
abas, blocos, cabeçalhos, contagens — com valores inventados. Nenhum extrato real, nem
anonimizado, entra no repositório; os asserts referenciam as constantes do gerador.
"""
import logging

import pytest

from app.tools.btg_xlsx_parser import ExtratoParseError, parse_btg_xlsx
from tests.gerador_extrato import (
    ALUGUEL_CONTRATADO_FIXTURE,
    DATA_ANTERIOR_FIXTURE,
    DATA_REFERENCIA_FIXTURE,
    LFT31_PRECO_COMPRA_FIXTURE,
    NTNB_CUSTO_TOTAL_FIXTURE,
    NTNB_PRECO_ATUAL_FIXTURE,
    NTNB_PRECO_MEDIO_FIXTURE,
    NTNB_QTDE_FIXTURE,
    NTNB_TAXA_FIXTURE,
    NTNB_VENCIMENTO_FIXTURE,
    PROVENTOS_LIQUIDOS_FIXTURE,
    RF_BRUTO_FIXTURE,
    CAIXA_FIM_FIXTURE,
    TAEE11_QTDE_FIXTURE,
    TAEE11_VALOR_FIXTURE,
    TOTAL_BRUTO_FIM_FIXTURE,
    TOTAL_BRUTO_INI_FIXTURE,
    TOTAL_POSICOES_FIXTURE,
    TOTAL_POSICOES_VALOR_FIXTURE,
    TRANSITO_FIXTURE,
)
from tests.planilhas import bytes_fixture

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def extrato():
    return parse_btg_xlsx(bytes_fixture())


def test_data_referencia(extrato):
    """A data vem do FIM do período ('Período de 01/07/26 a 31/07/26')."""
    assert extrato.data_referencia == DATA_REFERENCIA_FIXTURE
    assert all(p.as_of for p in extrato.posicoes), "toda posição precisa de as_of"


def test_posicoes_completas(extrato):
    """5 ações + 1 ETF + 3 FIIs + 5 Tesouro + 1 caixa = 15 posições."""
    por_classe: dict[str, int] = {}
    for p in extrato.posicoes:
        por_classe[p.classe] = por_classe.get(p.classe, 0) + 1

    assert por_classe == {"ACAO": 5, "ETF": 1, "FII": 3, "TESOURO": 5, "CAIXA": 1}
    assert len(extrato.posicoes) == TOTAL_POSICOES_FIXTURE
    assert not extrato.linhas_ignoradas, f"linhas não parseadas: {extrato.linhas_ignoradas}"


def test_checksum_bate_com_sumario(extrato):
    """Total das posições confere com a aba Sumario (descontados valores em trânsito
    e o resultado acumulado do aluguel, que o Sumário soma à RV)."""
    checagem = extrato.checagem
    assert checagem["ok"], checagem.get("aviso")
    assert checagem["total_parseado"] == pytest.approx(TOTAL_POSICOES_VALOR_FIXTURE, abs=0.01)
    assert checagem["valores_em_transito_excluidos"] == pytest.approx(TRANSITO_FIXTURE, abs=0.01)

    por_mercado = {c["mercado"]: c for c in checagem["por_mercado"]}
    assert por_mercado["Renda Fixa"]["parseado"] == pytest.approx(RF_BRUTO_FIXTURE, abs=0.01)
    assert por_mercado["Conta Corrente"]["parseado"] == pytest.approx(CAIXA_FIM_FIXTURE, abs=0.01)


def test_taee11_nao_duplica_com_aluguel(extrato):
    """
    TAEE11 aparece na posição de Ações E no bloco de aluguel como doador. Somar os dois
    duplicaria o papel — o aluguel é só informativo.
    """
    taee = [p for p in extrato.posicoes if p.ticker == "TAEE11"]
    assert len(taee) == 1, "TAEE11 duplicado — o bloco de aluguel virou posição"
    assert taee[0].valor_mercado == pytest.approx(TAEE11_VALOR_FIXTURE, abs=0.01)
    assert taee[0].quantidade == TAEE11_QTDE_FIXTURE

    assert len(extrato.aluguel) == 1
    assert extrato.aluguel[0]["ticker"] == "TAEE11"
    assert extrato.aluguel[0]["valor_contratado"] == pytest.approx(ALUGUEL_CONTRATADO_FIXTURE, abs=0.01)


def test_custo_de_aquisicao_do_tesouro(extrato):
    """
    preco_medio do Tesouro é o CUSTO médio ponderado dos lotes (aba Detalhamento),
    não o preço atual — este era o erro do parser de PDF. A NTNB-P da fixture tem
    4 lotes de aquisição somando o custo total do gerador.
    """
    ipca = next(p for p in extrato.posicoes if p.ticker == "Tesouro IPCA+ 2029")

    assert ipca.preco_medio == pytest.approx(NTNB_PRECO_MEDIO_FIXTURE, abs=0.05)
    assert ipca.preco_medio != pytest.approx(NTNB_PRECO_ATUAL_FIXTURE, abs=1.0), \
        "gravou o preço atual como custo"
    assert ipca.custo_total == pytest.approx(NTNB_CUSTO_TOTAL_FIXTURE, abs=0.01)
    assert ipca.preco_fechamento == pytest.approx(NTNB_PRECO_ATUAL_FIXTURE, abs=0.01)
    assert ipca.quantidade == pytest.approx(NTNB_QTDE_FIXTURE, abs=0.001)
    assert ipca.vencimento == NTNB_VENCIMENTO_FIXTURE
    assert "IPCA" in ipca.taxa_contratada
    assert ipca.taxa_contratada == NTNB_TAXA_FIXTURE


def test_tesouro_separa_vencimentos(extrato):
    """Duas LFTs (2028 e 2031) são posições distintas, com vencimento exato (G4)."""
    tesouro = {p.ticker: p for p in extrato.posicoes if p.classe == "TESOURO"}

    assert set(tesouro) == {
        "Tesouro Selic 2031", "Tesouro Selic 2028",
        "Tesouro Prefixado 2028", "Tesouro Prefixado 2029",
        "Tesouro IPCA+ 2029",
    }
    assert tesouro["Tesouro Selic 2031"].vencimento == "2031-03-01"
    assert tesouro["Tesouro Selic 2028"].vencimento == "2028-03-01"
    # lote único: o custo é o preço de compra declarado, sem erro de divisão
    assert tesouro["Tesouro Selic 2031"].preco_medio == pytest.approx(LFT31_PRECO_COMPRA_FIXTURE, abs=0.01)


def test_caixa_da_conta_corrente(extrato):
    """Conta corrente vira posição CAIXA; valores em trânsito ficam de fora."""
    caixa = [p for p in extrato.posicoes if p.classe == "CAIXA"]
    assert len(caixa) == 1
    assert caixa[0].ticker is None
    assert caixa[0].valor_mercado == pytest.approx(CAIXA_FIM_FIXTURE, abs=0.01)

    assert len(extrato.valores_em_transito) == 3
    total_transito = sum(v["valor"] for v in extrato.valores_em_transito)
    assert total_transito == pytest.approx(TRANSITO_FIXTURE, abs=0.01)
    com_transito = round(CAIXA_FIM_FIXTURE + TRANSITO_FIXTURE, 2)
    assert all(p.classe != "CAIXA" or p.valor_mercado != pytest.approx(com_transito, abs=0.01)
               for p in extrato.posicoes), "valores em trânsito entraram no caixa"


def test_proventos_do_mes(extrato):
    """JCP de ITUB4 + rendimentos dos 3 FIIs, líquidos."""
    assert len(extrato.proventos) == 4
    total_liquido = sum(p["valor_liquido"] for p in extrato.proventos)
    assert total_liquido == pytest.approx(PROVENTOS_LIQUIDOS_FIXTURE, abs=0.01)
    assert {p["ticker"] for p in extrato.proventos} == {"ITUB4", "KNCR11", "HGCR11", "RBRR11"}


def test_comparativo_mes_anterior(extrato):
    """A aba Sumario traz o mês anterior — base do comparativo mensal."""
    assert extrato.sumario["atual"]["data"] == DATA_REFERENCIA_FIXTURE
    assert extrato.sumario["anterior"]["data"] == DATA_ANTERIOR_FIXTURE
    assert extrato.sumario["atual"]["total"]["bruto"] == pytest.approx(TOTAL_BRUTO_FIM_FIXTURE, abs=0.01)
    assert extrato.sumario["anterior"]["total"]["bruto"] == pytest.approx(TOTAL_BRUTO_INI_FIXTURE, abs=0.01)


def test_nomes_com_espacos_colapsados(extrato):
    """'BRASIL      ON      NM' → 'BRASIL ON NM'."""
    bbas = next(p for p in extrato.posicoes if p.ticker == "BBAS3")
    assert bbas.nome == "BRASIL ON NM"
    assert "  " not in bbas.nome


def test_arquivo_invalido_nao_estoura():
    """Bytes que não são XLSX viram ExtratoParseError (a tool converte em tool_error)."""
    with pytest.raises(ExtratoParseError):
        parse_btg_xlsx(b"isto nao e um arquivo xlsx")


def test_xlsx_sem_as_abas_do_extrato(tmp_path):
    """Planilha válida mas sem a Capa do BTG → erro claro, sem inventar data."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Planilha1"
    wb.active["A1"] = "qualquer coisa"
    destino = tmp_path / "outra.xlsx"
    wb.save(destino)

    with pytest.raises(ExtratoParseError, match="Capa"):
        parse_btg_xlsx(destino.read_bytes())


def test_chave_externa_de_toda_posicao(extrato):
    """
    Identidade do papel entre extratos. O `nome` do BTG muda de mês para mês
    ('FII HGCR PAXCI' → 'FII HGCR PAXCI ER'), a chave não — é ela que o upsert usa.
    """
    chaves = {p.chave_externa for p in extrato.posicoes}
    assert None not in chaves, "toda posição do extrato precisa de chave"
    assert len(chaves) == len(extrato.posicoes), "chave repetida agregaria papéis distintos"

    por_ticker = {p.ticker: p.chave_externa for p in extrato.posicoes}
    assert por_ticker["BBAS3"] == "B3:BBAS3"
    assert por_ticker["Tesouro IPCA+ 2029"] == "TD:NTNB-P:2029-05-15"
    # Dois LFT no mesmo extrato: só o vencimento os separa
    assert por_ticker["Tesouro Selic 2028"] == "TD:LFT:2028-03-01"
    assert por_ticker["Tesouro Selic 2031"] == "TD:LFT:2031-03-01"

    caixa = next(p for p in extrato.posicoes if p.classe == "CAIXA")
    assert caixa.chave_externa == "CAIXA:BTG"


def test_chave_de_rf_privada_separa_emissores():
    """
    Dois CDBs com a mesma sigla e o mesmo vencimento, de bancos diferentes, são papéis
    diferentes — risco de crédito diferente. Antes eram agregados numa posição só.
    """
    from app.tools.btg_xlsx_parser import _chave_titulo

    xp = _chave_titulo(False, "BANCO XP S.A.", "CDB", "2027-06-15")
    brad = _chave_titulo(False, "BANCO BRADESCO", "CDB", "2027-06-15")
    assert xp != brad
    assert xp == "RF:BANCO-XP-S-A:CDB:2027-06-15"

    # Tesouro não leva emissor: é sempre o BACEN
    assert _chave_titulo(True, "BACEN-BANCO CENTRAL DO BRASIL", "LFT", "2031-03-01") == "TD:LFT:2031-03-01"
