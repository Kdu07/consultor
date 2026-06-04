"""
Validação da Fase 0: 1 cotação real (yfinance) + 1 macro real (Selic BCB).
Cada resultado aparece no log conforme exigido pelo PLANO §13 (Fase 0).
"""
import logging
import httpx
import pytest
from app.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)


def test_yfinance_petr4():
    """Valida que yfinance retorna um preço real para PETR4."""
    provider = YFinanceProvider()
    quote = provider.quote("PETR4")

    assert quote is not None, "yfinance não retornou cotação para PETR4 — verificar conectividade."
    assert quote.price > 0, f"Preço inválido: {quote.price}"
    assert quote.source == "yfinance"
    assert quote.ticker == "PETR4"

    logger.info(
        "[VALIDACAO Fase 0] yfinance: %s = R$ %.2f (source=%s, as_of=%s)",
        quote.ticker, quote.price, quote.source,
        quote.as_of.strftime("%Y-%m-%d %H:%M"),
    )
    print(f"\n[OK] yfinance -- PETR4: R$ {quote.price:.2f} ({quote.as_of.strftime('%Y-%m-%d %H:%M')})")


def test_bcb_selic():
    """Valida que a API pública do BCB retorna a Selic atual (série 11)."""
    resp = httpx.get(
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json",
        timeout=10.0,
    )
    assert resp.status_code == 200, f"BCB retornou status {resp.status_code}"
    data = resp.json()
    assert len(data) > 0, "BCB retornou lista vazia."

    valor = data[0]["valor"]
    data_ref = data[0]["data"]
    assert float(valor) > 0, f"Selic inválida: {valor}"

    logger.info(
        "[VALIDACAO Fase 0] BCB/SGS Selic: %s%% a.a. (data referencia: %s)",
        valor, data_ref,
    )
    print(f"\n[OK] BCB -- Selic: {valor}% a.a. (ref. {data_ref})")


def test_models_create_tables(tmp_path):
    """Valida que create_tables() cria o schema sem erros."""
    import os
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/test.db"

    # Limpa cache do lru_cache para usar o DATABASE_URL do teste
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import _make_engine
    from sqlmodel import SQLModel, Session, select
    from app.models import Posicao, ClasseAtivo, ConfigRebalanceamento

    engine = _make_engine()
    from app.models import (
        AlvoClasse, AlvoAtivo, PerfilRisco,
        QuoteCache, SnapshotMensal,
        EstrategiaInvestimento, PlanoFuturo, HistoricoEstrategia,
    )
    SQLModel.metadata.create_all(engine)

    # Insere e lê 1 Posicao
    with Session(engine) as session:
        pos = Posicao(nome="PETR4 teste", ticker="PETR4", classe=ClasseAtivo.ACAO, quantidade=100)
        session.add(pos)
        session.commit()
        session.refresh(pos)
        assert pos.id is not None

        found = session.exec(select(Posicao).where(Posicao.ticker == "PETR4")).first()
        assert found is not None
        assert found.quantidade == 100

    logger.info("[VALIDACAO Fase 0] SQLite: tabelas criadas e Posicao inserida/lida com sucesso.")
    print("\n[OK] SQLite -- tabelas criadas, Posicao inserida e lida.")

    # Restaura env
    os.environ.pop("DATABASE_URL", None)
    get_settings.cache_clear()
