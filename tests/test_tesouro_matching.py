"""
Casamento de títulos do Tesouro por (tipo, ano) — gap G4 (PLANO_XLSX, Bloco 6b).

Sem rede: o índice do provider é populado à mão com nomes reais da lista do Tesouro
Direto. O que se testa aqui é a REGRA de casamento, não a disponibilidade da fonte.
"""
import pytest

from app.providers.tesouro_provider import TesouroProvider, _chave

# Nomes como aparecem na lista pública do Tesouro Direto
TITULOS_OFICIAIS = [
    "Tesouro Selic 2028",
    "Tesouro Selic 2031",
    "Tesouro Prefixado 2028",
    "Tesouro Prefixado 2029",
    "Tesouro Prefixado com Juros Semestrais 2035",
    "Tesouro IPCA+ 2029",
    "Tesouro IPCA+ 2035",
    "Tesouro IPCA+ com Juros Semestrais 2035",
]


@pytest.fixture
def provider():
    p = TesouroProvider()
    p._cache = {nome.upper(): {"nm": nome, "untrInvstmtVal": 1000.0} for nome in TITULOS_OFICIAIS}
    p._por_chave = {_chave(nome): {"nm": nome, "untrInvstmtVal": 1000.0} for nome in TITULOS_OFICIAIS}
    yield p
    p._cache = {}
    p._por_chave = {}


def test_chave_separa_tipo_e_ano():
    assert _chave("Tesouro IPCA+ 2029") == ("tesouro ipca", "2029")
    assert _chave("TESOURO IPCA 2029") == ("tesouro ipca", "2029")
    assert _chave("Tesouro Selic 2031") == ("tesouro selic", "2031")


@pytest.mark.parametrize("nome_do_extrato,esperado", [
    # nomes exatamente como o parser XLSX os monta (sigla + ano do vencimento)
    ("Tesouro Selic 2031", "Tesouro Selic 2031"),
    ("Tesouro Selic 2028", "Tesouro Selic 2028"),
    ("Tesouro Prefixado 2028", "Tesouro Prefixado 2028"),
    ("Tesouro Prefixado 2029", "Tesouro Prefixado 2029"),
    ("Tesouro IPCA+ 2029", "Tesouro IPCA+ 2029"),
    # variações de digitação que o usuário pode usar no chat
    ("TESOURO IPCA 2029", "Tesouro IPCA+ 2029"),
    ("tesouro ipca+ 2035", "Tesouro IPCA+ 2035"),
])
def test_casa_titulos_do_extrato(provider, nome_do_extrato, esperado):
    bond = provider._find(nome_do_extrato)
    assert bond is not None, f"não casou: {nome_do_extrato}"
    assert bond["nm"] == esperado


def test_nao_confunde_principal_com_juros_semestrais(provider):
    """
    NTNB-P (principal) e NTNB (juros semestrais) do mesmo ano são títulos diferentes,
    com preços diferentes. Casar um pelo outro seria erro de valoração.
    """
    assert provider._find("Tesouro IPCA+ 2035")["nm"] == "Tesouro IPCA+ 2035"
    assert provider._find("Tesouro IPCA+ com Juros Semestrais 2035")["nm"] == \
        "Tesouro IPCA+ com Juros Semestrais 2035"


def test_titulo_ausente_devolve_none(provider):
    """Título fora de negociação não casa — o chamador cai para o valor do extrato."""
    assert provider._find("Tesouro Selic 2027") is None
    assert provider._find("Tesouro IPCA+ 2045") is None
