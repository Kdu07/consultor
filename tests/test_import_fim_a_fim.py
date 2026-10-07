"""
Import de ponta a ponta: XLSX → preview → gravar_posicoes → calcular_desvio
(PLANO_XLSX, Bloco 6). Roda contra um banco temporário, nunca contra data/carteira.db.

Protege o que a migração para XLSX trouxe de novo para o banco: custo real do Tesouro,
vencimento, taxa contratada e a posição de CAIXA convivendo com o cálculo de desvio.
"""
import logging
import os

import pytest

from tests.gerador_extrato import (
    CAIXA_FIM_FIXTURE,
    NTNB_PRECO_MEDIO_FIXTURE,
    NTNB_TAXA_FIXTURE,
)
from tests.planilhas import bytes_fixture

logger = logging.getLogger(__name__)


@pytest.fixture
def banco_temporario(tmp_path, monkeypatch):
    """Aponta o app para um SQLite descartável e recria o schema."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")

    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    from sqlmodel import SQLModel
    import app.models  # noqa: F401 — registra as tabelas no metadata

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    # As tools importam `engine` diretamente do módulo database
    import app.tools.gravar as gravar_mod
    import app.tools.desvio as desvio_mod
    monkeypatch.setattr(gravar_mod, "engine", engine)
    monkeypatch.setattr(desvio_mod, "engine", engine)

    yield engine
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def staging_limpo():
    """O staging é singleton de processo — não pode vazar de um teste para o outro."""
    from app.tools import extrato_staging

    extrato_staging.clear()
    yield
    extrato_staging.clear()


@pytest.fixture
def preview():
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.extrato import montar_preview

    return montar_preview(parse_btg_xlsx(bytes_fixture()), "extrato_exemplo.xlsx")


@pytest.fixture
def preview_em_staging(preview):
    """Reproduz o fluxo real: o upload deixa o preview em staging antes da confirmação."""
    from app.tools import extrato_staging

    extrato_staging.set_preview(preview, "extrato_exemplo.xlsx")
    return preview


def _posicao_orfa(engine, nome="CDB Banco XP 120pct CDI"):
    """Posição que existe na carteira e não aparece no extrato (ex.: seed antigo)."""
    from sqlmodel import Session
    from app.models.posicao import ClasseAtivo, Posicao

    with Session(engine) as s:
        s.add(Posicao(nome=nome, classe=ClasseAtivo.RF, quantidade=1.0, valor_mercado=25000.0))
        s.commit()


async def test_grava_as_15_posicoes(banco_temporario, preview):
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools.gravar import tool_gravar_posicoes

    resultado = await tool_gravar_posicoes(preview["posicoes"])

    assert resultado["total_gravadas"] == 15
    assert resultado["posicoes_criadas"] == 15
    assert "avisos" not in resultado, resultado.get("avisos")

    with Session(banco_temporario) as s:
        posicoes = s.exec(select(Posicao)).all()
        assert len(posicoes) == 15

        ipca = next(p for p in posicoes if p.ticker == "Tesouro IPCA+ 2029")
        assert ipca.preco_medio == pytest.approx(NTNB_PRECO_MEDIO_FIXTURE, abs=0.05)   # custo, não preço atual
        assert ipca.vencimento is not None and ipca.vencimento.year == 2029
        assert ipca.taxa_contratada == NTNB_TAXA_FIXTURE

        caixa = next(p for p in posicoes if p.classe.value == "CAIXA")
        assert caixa.valor_mercado == pytest.approx(CAIXA_FIM_FIXTURE, abs=0.01)
        assert caixa.ticker is None

        acao = next(p for p in posicoes if p.ticker == "BBAS3")
        assert acao.vencimento is None and acao.taxa_contratada is None


async def test_reimportar_o_mesmo_extrato_e_idempotente(banco_temporario, preview):
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes(preview["posicoes"])
    segundo = await tool_gravar_posicoes(preview["posicoes"])

    assert segundo["posicoes_criadas"] == 0
    assert segundo["posicoes_atualizadas"] == 15

    with Session(banco_temporario) as s:
        assert len(s.exec(select(Posicao)).all()) == 15


async def test_extrato_desativa_posicao_que_sumiu(banco_temporario, preview_em_staging):
    """
    O extrato é a carteira completa: o que não está nele saiu (venda, resgate, seed antigo).
    Sem isso a carteira só cresce e o dashboard soma patrimônio que não existe mais.
    """
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools.gravar import tool_gravar_posicoes

    _posicao_orfa(banco_temporario)

    resultado = await tool_gravar_posicoes()

    assert resultado["total_gravadas"] == 15
    desativadas = resultado["posicoes_desativadas"]
    assert [d["nome"] for d in desativadas] == ["CDB Banco XP 120pct CDI"]
    assert desativadas[0]["ultimo_valor"] == 25000.0
    # O agente precisa contar isso ao usuário — o aviso é o gatilho no prompt
    assert any("saíram da carteira" in a for a in resultado["avisos"])

    with Session(banco_temporario) as s:
        ativas = s.exec(select(Posicao).where(Posicao.ativo == True)).all()
        assert len(ativas) == 15
        assert all(p.nome != "CDB Banco XP 120pct CDI" for p in ativas)
        # desativada, não apagada: o histórico continua no banco
        assert len(s.exec(select(Posicao)).all()) == 16


async def test_nome_reescrito_pelo_btg_atualiza_a_mesma_posicao(banco_temporario, preview_em_staging):
    """
    O BTG reescreve o nome do papel entre extratos: 'ITAUUNIBANCOPN N1' vira
    'ITAUUNIBANCOPN EJ N1' quando o papel fica ex-juros, 'FII HGCR PAXCI' vira
    'FII HGCR PAXCI ER'. Casando por nome, a posição antiga era abandonada e outra
    nascia no lugar — dois ITUB4 na carteira. A chave_externa é o que não muda.
    """
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes()

    with Session(banco_temporario) as s:
        antes = s.exec(select(Posicao).where(Posicao.ticker == "ITUB4")).one()
        id_original, criado_em = antes.id, antes.criado_em

    # Mês seguinte: mesmos papéis, dois nomes reescritos pelo BTG
    mes_seguinte = {**preview_em_staging, "posicoes": [dict(p) for p in preview_em_staging["posicoes"]]}
    for p in mes_seguinte["posicoes"]:
        if p["ticker"] == "ITUB4":
            p["nome"] = "ITAUUNIBANCOPN EJ N1"
        if p["ticker"] == "HGCR11":
            p["nome"] = "FII HGCR PAXCI ER"
    extrato_staging.set_preview(mes_seguinte, "mes_seguinte.xlsx")

    resultado = await tool_gravar_posicoes()

    assert resultado["posicoes_criadas"] == 0, "nome novo não pode criar posição nova"
    assert resultado["posicoes_atualizadas"] == 15
    assert resultado["posicoes_desativadas"] == []

    with Session(banco_temporario) as s:
        depois = s.exec(select(Posicao).where(Posicao.ticker == "ITUB4")).one()
        assert depois.id == id_original, "a posição precisa ser a mesma linha"
        assert depois.criado_em == criado_em, "histórico preservado"
        assert depois.nome == "ITAUUNIBANCOPN EJ N1"
        assert len(s.exec(select(Posicao)).all()) == 15


async def test_papel_que_volta_reativa_a_linha_original(banco_temporario, preview_em_staging):
    """
    Vendeu num mês, recomprou no outro. A linha desativada tem a mesma chave: reativa,
    não cria uma segunda. Senão o mesmo papel acumularia uma linha por ida e volta.
    """
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes()
    with Session(banco_temporario) as s:
        id_original = s.exec(select(Posicao).where(Posicao.ticker == "VALE3")).one().id

    # Mês 2: sem VALE3
    sem_vale = {**preview_em_staging,
                "posicoes": [p for p in preview_em_staging["posicoes"] if p["ticker"] != "VALE3"]}
    extrato_staging.set_preview(sem_vale, "mes2.xlsx")
    r2 = await tool_gravar_posicoes()
    assert [d["ticker"] for d in r2["posicoes_desativadas"]] == ["VALE3"]

    # Mês 3: VALE3 de volta
    extrato_staging.set_preview(preview_em_staging, "mes3.xlsx")
    r3 = await tool_gravar_posicoes()

    assert r3["posicoes_criadas"] == 0, "papel que volta reativa, não cria linha nova"
    assert r3["posicoes_reativadas"] == ["VALE3"]
    assert any("Voltaram à carteira" in a for a in r3["avisos"])

    with Session(banco_temporario) as s:
        vale = s.exec(select(Posicao).where(Posicao.ticker == "VALE3")).all()
        assert len(vale) == 1, "uma linha por papel, mesmo depois de ida e volta"
        assert vale[0].id == id_original and vale[0].ativo is True


async def test_posicao_antiga_sem_chave_e_adotada(banco_temporario, preview_em_staging):
    """
    Linha anterior à migração (chave nula) é adotada pelo ticker no primeiro import e
    passa a carregar a chave — o backfill acontece sozinho, sem adivinhar papel por nome.
    """
    from sqlmodel import Session, select
    from app.models.posicao import ClasseAtivo, Posicao
    from app.tools.gravar import tool_gravar_posicoes

    with Session(banco_temporario) as s:
        s.add(Posicao(ticker="BBAS3", nome="BRASIL ON NM", classe=ClasseAtivo.ACAO,
                      quantidade=100.0, valor_mercado=2000.0))
        s.commit()
        id_legado = s.exec(select(Posicao).where(Posicao.ticker == "BBAS3")).one().id

    resultado = await tool_gravar_posicoes()

    assert resultado["posicoes_criadas"] == 14, "a linha legada é adotada, não duplicada"
    with Session(banco_temporario) as s:
        bbas = s.exec(select(Posicao).where(Posicao.ticker == "BBAS3")).one()
        assert bbas.id == id_legado
        assert bbas.chave_externa == "B3:BBAS3"


async def test_lista_do_modelo_nao_sobrepoe_o_extrato(banco_temporario, preview_em_staging):
    """
    Se o modelo truncar a lista no argumento da tool, o staging prevalece — senão a
    reconciliação desativaria posições que na verdade estão no extrato.
    """
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools.gravar import tool_gravar_posicoes

    truncada = preview_em_staging["posicoes"][:2]
    resultado = await tool_gravar_posicoes(truncada)

    assert resultado["total_gravadas"] == 15
    assert any("2 posição(ões)" in a for a in resultado["avisos"])

    with Session(banco_temporario) as s:
        assert len(s.exec(select(Posicao).where(Posicao.ativo == True)).all()) == 15


async def test_gravacao_manual_nao_desativa_nada(banco_temporario, preview):
    """Sem extrato em staging o lote é parcial por natureza: só upsert, nunca baixa."""
    from sqlmodel import Session, select
    from app.models.posicao import Posicao
    from app.tools.gravar import tool_gravar_posicoes

    _posicao_orfa(banco_temporario)

    resultado = await tool_gravar_posicoes(preview["posicoes"])

    assert resultado["posicoes_desativadas"] == []
    with Session(banco_temporario) as s:
        assert len(s.exec(select(Posicao).where(Posicao.ativo == True)).all()) == 16


async def test_preview_e_consumido_na_gravacao(banco_temporario, preview_em_staging):
    """Preview é de uso único: gravado, sai do staging."""
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes()

    assert extrato_staging.get() is None


async def test_desvio_com_caixa_sem_alvo(banco_temporario, preview):
    """
    CAIXA entra no total da carteira, mas não tem alvo cadastrado: alvo indefinido não
    é alvo 0%. O desvio dele fica None e a classe é marcada — senão o modelo poderia
    ler '+0,6 p.p. acima do alvo' e sugerir zerar o caixa.
    """
    from app.tools.gravar import tool_gravar_posicoes
    from app.tools.desvio import tool_calcular_desvio

    await tool_gravar_posicoes(preview["posicoes"])
    resultado = await tool_calcular_desvio()

    assert "error" not in resultado, resultado
    total = resultado["snapshot"]["valor_total"]
    assert total > 0

    caixa = next(c for c in resultado["por_classe"] if c["classe"] == "CAIXA")
    assert caixa["valor"] == pytest.approx(CAIXA_FIM_FIXTURE, abs=0.01)
    assert caixa["sem_alvo_definido"] is True
    assert caixa["percentual_alvo"] is None
    assert caixa["desvio_pp"] is None
    assert caixa["fora_da_banda"] is None
    assert "CAIXA" in resultado["classes_sem_alvo"]

    logger.info(
        "[XLSX] desvio com caixa: total=R$ %.2f | classes sem alvo: %s",
        total, resultado["classes_sem_alvo"],
    )
