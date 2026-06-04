import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session
from .config import get_settings


def _make_engine():
    settings = get_settings()
    url = settings.database_url

    # Garante que a pasta data/ existe antes de criar o arquivo SQLite
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if "sqlite" in url else {}
    return create_engine(url, connect_args=connect_args, echo=False)


engine = _make_engine()


def create_tables() -> None:
    """Cria todas as tabelas definidas nos modelos SQLModel."""
    # Importar todos os modelos para que o SQLModel os registre
    from .models import (  # noqa: F401
        Posicao, AlvoClasse, AlvoAtivo, ConfigRebalanceamento,
        PerfilRisco, QuoteCache, SnapshotMensal,
        EstrategiaInvestimento, PlanoFuturo, HistoricoEstrategia,
    )
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
