"""
Classificação dos lançamentos do razão (docs/PLANO_HISTORICO.md, Bloco 2).

O que importa para a rentabilidade é a fronteira externo × interno: um aporte tratado como
interno vira "rendimento" que a carteira nunca teve. Estes testes protegem essa fronteira, a
ordem de precedência das regras e a classificação retroativa (regra nova vale para meses já
arquivados, porque nada é gravado no extrato).
"""
from datetime import date

import pytest

from app.tools.lancamentos import (
    APORTE,
    NAO_CLASSIFICADO,
    PROVENTO,
    RENDIMENTO_CAIXA,
    RESGATE,
    TAXA,
    Regra,
    chave_de_texto,
    classificar,
    classificar_mes,
    fluxos_externos,
    impressao_linha,
    padrao_sugerido,
)
from tests.planilhas import bytes_fixture


def _l(descricao: str, valor: float, seq: int = 0, data: str = "2026-07-10") -> dict:
    return {"seq": seq, "data": data, "descricao": descricao, "valor": valor, "saldo": None}


# ---------------------------------------------------------------------------
# Regras padrão
# ---------------------------------------------------------------------------

def test_fixture_tem_4_proventos_e_o_rendimento_do_saldo():
    from app.tools.btg_xlsx_parser import parse_btg_xlsx

    extrato = parse_btg_xlsx(bytes_fixture())
    tipos = [c["tipo"] for c in classificar_mes(extrato.data_referencia, extrato.lancamentos_conta)]
    assert tipos == [PROVENTO, PROVENTO, PROVENTO, PROVENTO, RENDIMENTO_CAIXA]
    assert fluxos_externos(classificar_mes(None, extrato.lancamentos_conta)) == []


@pytest.mark.parametrize("descricao, valor, tipo", [
    ("PIX RECEBIDO", 2000.0, APORTE),
    ("PIX ENVIADO", -300.0, RESGATE),
    ("TED ENVIADA", -500.0, RESGATE),
    ("TED RECEBIDA", 500.0, APORTE),
    ("TRANSFERENCIA ENTRE CONTAS RECEBIDO", 100.0, APORTE),
    ("DEVOLUÇÃO TED", 500.0, APORTE),           # volta de dinheiro: entra pelo sinal
    ("TRANSF CUSTODIA RECEBIDA", 3500.0, NAO_CLASSIFICADO),   # move ativo, não dinheiro
    ("TAXA DE CUSTODIA", -10.0, TAXA),
    ("UMA LINHA QUE O BTG AINDA NAO MOSTROU", -42.0, NAO_CLASSIFICADO),
])
def test_regras_padrao(descricao, valor, tipo):
    assert classificar(_l(descricao, valor)).tipo == tipo


def test_fluxo_externo_usa_o_sinal_do_razao():
    """Mesmo rotulado como APORTE, um débito entra negativo — o valor manda."""
    regras = [Regra(tipo=APORTE, modo="exato", padrao=chave_de_texto("ESTORNO X"), id=1)]
    classificados = classificar_mes("2026-07-31", [_l("ESTORNO X", -200.0)], regras)
    assert fluxos_externos(classificados) == [("2026-07-10", -200.0)]


def test_padrao_sugerido_corta_antes_do_que_varia():
    assert padrao_sugerido("JUROS S/ CAPITAL - À VISTA s/ ITAUUNIBANCOPN N1 - ITUB4") == "juros s/ capital"
    assert padrao_sugerido("Saldo Final + Rendimento Provisionado") == "saldo final"
    assert padrao_sugerido("LIQUIDACAO BOLSA 10/07") == "liquidacao bolsa"


# ---------------------------------------------------------------------------
# Precedência
# ---------------------------------------------------------------------------

def test_regra_do_dono_vence_a_padrao():
    regras = [Regra(tipo=RESGATE, modo="prefixo", padrao="pix", id=7)]
    c = classificar(_l("PIX RECEBIDO", 50.0), regras)
    assert (c.tipo, c.origem, c.regra_id) == (RESGATE, "regra", 7)


def test_exato_vence_prefixo_e_prefixo_mais_longo_vence():
    regras = [
        Regra(tipo=TAXA, modo="prefixo", padrao="servico", id=1),
        Regra(tipo=PROVENTO, modo="prefixo", padrao="servico de renda", id=2),
        Regra(tipo=APORTE, modo="exato", padrao="servico de renda extra", id=3),
    ]
    assert classificar(_l("SERVICO DE RENDA EXTRA", 1.0), regras).regra_id == 3
    assert classificar(_l("SERVICO DE RENDA MENSAL", 1.0), regras).regra_id == 2
    assert classificar(_l("SERVICO QUALQUER", 1.0), regras).regra_id == 1


def test_contem_casa_palavra_inteira():
    regras = [Regra(tipo=TAXA, modo="contem", padrao="ted", id=1)]
    assert classificar(_l("ALGO TED ALGO", -1.0), regras).regra_id == 1
    assert classificar(_l("CONTEDUDO", -1.0), regras).tipo == NAO_CLASSIFICADO


def test_regra_com_sinal_so_vale_para_aquele_lado():
    regras = [Regra(tipo=APORTE, modo="prefixo", padrao="credito em conta", sinal="credito", id=1)]
    assert classificar(_l("CREDITO EM CONTA", 10.0), regras).tipo == APORTE
    assert classificar(_l("CREDITO EM CONTA", -10.0), regras).tipo == NAO_CLASSIFICADO


def test_regra_de_linha_vale_enquanto_a_linha_nao_muda():
    linha = _l("UMA LINHA QUE O BTG AINDA NAO MOSTROU", -42.0, seq=3)
    regra = Regra(tipo=RESGATE, escopo="linha", data_referencia="2026-07-31", seq=3,
                  impressao=impressao_linha("2026-07-31", linha), id=9)

    c = classificar(linha, [regra], data_referencia="2026-07-31")
    assert (c.tipo, c.origem) == (RESGATE, "linha")

    # Mês reimportado com outra linha na mesma posição: a regra antiga não vale mais.
    outra = {**linha, "valor": -43.0}
    assert classificar(outra, [regra], data_referencia="2026-07-31").tipo == NAO_CLASSIFICADO
    # E não vaza para outro mês.
    assert classificar(linha, [regra], data_referencia="2026-08-31").tipo == NAO_CLASSIFICADO


# ---------------------------------------------------------------------------
# Persistência — regras do dono
# ---------------------------------------------------------------------------

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


def test_regra_nova_reclassifica_mes_ja_arquivado(banco):
    """Nada é gravado no extrato: a regra criada depois muda a leitura seguinte."""
    from sqlmodel import Session
    from app.tools import regras_lancamento

    arquivado = [_l("LINHA ESTRANHA DO BTG", 1500.0)]
    antes = classificar_mes("2026-07-31", arquivado, regras_lancamento.carregar_regras_seguro())
    assert antes[0]["tipo"] == NAO_CLASSIFICADO

    with Session(banco) as s:
        regras_lancamento.criar_ou_atualizar(s, tipo=APORTE, modo="prefixo", padrao="LINHA ESTRANHA")
        s.commit()

    depois = classificar_mes("2026-07-31", arquivado, regras_lancamento.carregar_regras_seguro())
    assert depois[0]["tipo"] == APORTE
    assert depois[0]["origem"] == "regra"
    assert fluxos_externos(depois) == [("2026-07-10", 1500.0)]


def test_mesma_regra_de_texto_atualiza_em_vez_de_duplicar(banco):
    from sqlmodel import Session
    from app.tools import regras_lancamento

    with Session(banco) as s:
        r1, nova1 = regras_lancamento.criar_ou_atualizar(s, tipo=APORTE, padrao="Linha X")
        r2, nova2 = regras_lancamento.criar_ou_atualizar(s, tipo=RESGATE, padrao="linha x")
        s.commit()
        assert (nova1, nova2) == (True, False)
        assert r1.id == r2.id
        assert len(regras_lancamento.listar(s)) == 1
        assert regras_lancamento.listar(s)[0].tipo == RESGATE


def test_regra_de_linha_guarda_a_impressao(banco):
    from sqlmodel import Session
    from app.tools import regras_lancamento

    linha = _l("UMA LINHA", -42.0, seq=2)
    with Session(banco) as s:
        regra, _ = regras_lancamento.criar_ou_atualizar(
            s, tipo=RESGATE, escopo="linha", data_referencia=date(2026, 7, 31), seq=2, lancamento=linha,
        )
        s.commit()
        assert regra.impressao == impressao_linha("2026-07-31", linha)

    regras = regras_lancamento.carregar_regras_seguro()
    assert classificar(linha, regras, data_referencia="2026-07-31").tipo == RESGATE


@pytest.mark.parametrize("dados", [
    {"tipo": "INVENTADO", "padrao": "x"},
    {"tipo": APORTE, "padrao": "   "},
    {"tipo": APORTE, "padrao": "x", "modo": "regex"},
    {"tipo": APORTE, "escopo": "linha"},
    {"tipo": APORTE, "escopo": "ativo_mes", "padrao": "B3:BBAS3", "data_referencia": date(2026, 7, 31)},
])
def test_regra_invalida_e_recusada(banco, dados):
    from sqlmodel import Session
    from app.tools import regras_lancamento

    with Session(banco) as s, pytest.raises(regras_lancamento.RegraInvalida):
        regras_lancamento.criar_ou_atualizar(s, **dados)


def test_excluir_do_mes_leva_so_as_regras_presas_ao_mes(banco):
    from sqlmodel import Session
    from app.tools import regras_lancamento

    with Session(banco) as s:
        regras_lancamento.criar_ou_atualizar(s, tipo=APORTE, padrao="linha x")
        regras_lancamento.criar_ou_atualizar(
            s, tipo=RESGATE, escopo="linha", data_referencia=date(2026, 7, 31), seq=0,
            lancamento=_l("UMA LINHA", -1.0),
        )
        regras_lancamento.criar_ou_atualizar(
            s, tipo=regras_lancamento.EVENTO_SOCIETARIO, escopo="ativo_mes",
            data_referencia=date(2026, 7, 31), padrao="B3:BBAS3",
        )
        s.commit()
        assert regras_lancamento.excluir_do_mes(s, date(2026, 7, 31)) == 2
        s.commit()
        assert [r.escopo for r in regras_lancamento.listar(s)] == ["texto"]


def test_sem_tabela_as_regras_do_dono_ficam_vazias(tmp_path, monkeypatch):
    """O upload não pode quebrar porque o banco ainda não tem a tabela de regras."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/vazio.db")
    from app.config import get_settings
    get_settings.cache_clear()
    import app.database as database
    from app.tools import regras_lancamento

    monkeypatch.setattr(database, "engine", database._make_engine())
    try:
        assert regras_lancamento.carregar_regras_seguro() == []
    finally:
        get_settings.cache_clear()
