"""
Data de corte do import (docs/PLANO_HISTORICO.md, decisão técnica 1).

O bug que estes testes fecham: o modo somente-histórico só olhava o extrato arquivado mais
recente. Produção, em 10/2026, não tinha nenhum arquivado — e a carteira refletia o extrato
de 2026-08-10. Importar junho pelo chat teria reconciliado a carteira para trás.
"""
from datetime import date, datetime, timezone

import pytest

from tests.planilhas import bytes_fixture


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


@pytest.fixture(autouse=True)
def staging_limpo():
    from app.tools import extrato_staging

    extrato_staging.clear()
    yield
    extrato_staging.clear()


def _carteira_de_producao(engine):
    """As 15 posições do extrato de julho, mas com o as_of de 2026-08-10, sem nada arquivado."""
    from sqlmodel import Session
    from app.models.posicao import ClasseAtivo, Posicao
    from app.tools.btg_xlsx_parser import parse_btg_xlsx

    extrato = parse_btg_xlsx(bytes_fixture())
    with Session(engine) as s:
        for p in extrato.posicoes:
            s.add(Posicao(
                ticker=p.ticker, nome=p.nome, classe=ClasseAtivo(p.classe), quantidade=p.quantidade,
                valor_mercado=p.valor_mercado, chave_externa=p.chave_externa, source="extrato",
                as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ))
        s.commit()
    return extrato


def _em_staging(extrato, data_referencia: str | None = None):
    from app.tools import extrato_staging
    from app.tools.extrato import montar_preview

    preview = montar_preview(extrato, "extrato.xlsx")
    bruto = extrato.to_dict()
    if data_referencia:
        preview = {**preview, "data_referencia": data_referencia}
        bruto = {**bruto, "data_referencia": data_referencia}
    extrato_staging.set_preview(preview, "extrato.xlsx", bruto=bruto)


def _ativas(engine) -> dict:
    from sqlmodel import Session, select
    from app.models.posicao import Posicao

    with Session(engine) as s:
        return {p.chave_externa: (p.quantidade, p.valor_mercado, p.as_of)
                for p in s.exec(select(Posicao).where(Posicao.ativo == True)).all()}  # noqa: E712


async def test_cenario_de_producao_mes_antigo_nao_reconcilia(banco):
    from app.tools.gravar import tool_gravar_posicoes

    extrato = _carteira_de_producao(banco)
    antes = _ativas(banco)

    _em_staging(extrato)   # julho: anterior a 2026-08-10
    resultado = await tool_gravar_posicoes()

    assert resultado["modo"] == "somente_historico"
    assert resultado["carteira_alterada"] is False
    assert any("2026-08-10" in a for a in resultado["avisos"])
    assert _ativas(banco) == antes
    assert resultado["extrato_arquivado"]["data_referencia"] == "2026-07-31"


async def test_import_no_modo_normal_registra_a_referencia(banco):
    from sqlmodel import Session
    from app.tools.extrato_arquivo import data_de_corte, referencia_da_carteira
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.gravar import tool_gravar_posicoes

    _em_staging(parse_btg_xlsx(bytes_fixture()))
    resultado = await tool_gravar_posicoes()
    assert "modo" not in resultado

    with Session(banco) as s:
        assert referencia_da_carteira(s) == date(2026, 7, 31)
        assert data_de_corte(s) == date(2026, 7, 31)


async def test_edicao_manual_nao_move_o_corte(banco):
    """Com a referência semeada, um as_of novo vindo de edição manual não muda o corte."""
    from sqlmodel import Session
    from app.seeds import _seed_referencia_carteira
    from app.tools.extrato_arquivo import data_de_corte
    from app.tools.gravar import tool_gravar_posicoes

    _carteira_de_producao(banco)
    with Session(banco) as s:
        _seed_referencia_carteira(s)
        s.commit()
        assert data_de_corte(s) == date(2026, 8, 10)

    # "comprei mais 10 BBAS3 hoje" — gravação manual, com o as_of que o modelo mandou
    await tool_gravar_posicoes([{
        "ticker": "BBAS3", "nome": "BRASIL ON NM", "classe": "ACAO", "quantidade": 110,
        "valor_mercado": 2400.0, "as_of": "2026-10-05",
    }])

    with Session(banco) as s:
        assert data_de_corte(s) == date(2026, 8, 10)


async def test_semente_nao_inventa_referencia_em_carteira_so_manual(banco):
    from sqlmodel import Session
    from app.seeds import _seed_referencia_carteira
    from app.tools.extrato_arquivo import data_de_corte
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes([{
        "ticker": "PETR4", "nome": "PETROBRAS PN", "classe": "ACAO", "quantidade": 100,
        "valor_mercado": 3800.0, "as_of": "2026-10-05",
    }])
    with Session(banco) as s:
        _seed_referencia_carteira(s)
        s.commit()
        assert data_de_corte(s) is None, "posição manual não tem chave_externa: não define o corte"


async def test_mes_igual_ao_corte_reimporta_normalmente(banco):
    """Reenviar o extrato do mês que a carteira já reflete é correção, não histórico."""
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.gravar import tool_gravar_posicoes

    extrato = parse_btg_xlsx(bytes_fixture())
    _em_staging(extrato)
    await tool_gravar_posicoes()
    _em_staging(extrato)
    resultado = await tool_gravar_posicoes()
    assert "modo" not in resultado
    assert resultado["extrato_arquivado"]["acao"] == "atualizado"
