import os
from pathlib import Path
from sqlalchemy import event
from sqlmodel import SQLModel, create_engine, Session
from .config import get_settings


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    is_sqlite = "sqlite" in url

    # Garante que a pasta data/ existe antes de criar o arquivo SQLite
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    # timeout: o uvicorn atende requests em threads; sem espera, escrita concorrente
    # vira "database is locked" na hora.
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    eng = create_engine(url, connect_args=connect_args, echo=False)

    if is_sqlite:
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - infra
            cur = dbapi_conn.cursor()
            # WAL: leitores não bloqueiam o escritor (e vice-versa).
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = _make_engine()


def create_tables() -> None:
    """Cria todas as tabelas definidas nos modelos SQLModel."""
    # Importar todos os modelos para que o SQLModel os registre
    from .models import (  # noqa: F401
        Posicao, AlvoClasse, AlvoAtivo, ConfigRebalanceamento,
        PerfilRisco, QuoteCache, SnapshotMensal, ExtratoImportado, RegraLancamento,
        ReferenciaCarteira, IndicadorMensal,
        EstrategiaInvestimento, PlanoFuturo, HistoricoEstrategia,
    )
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
