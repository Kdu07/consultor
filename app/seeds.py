"""
Semeia dados iniciais no banco se ainda não existirem.
Roda uma vez no startup; idempotente.
"""
import logging
from pathlib import Path
from sqlmodel import Session, select
from .database import engine
from .models import (
    ConfigRebalanceamento,
    PerfilRisco,
    AlvoClasse,
    ClasseAtivo,
)

logger = logging.getLogger(__name__)

_PERFIL_RISCO_PATH = Path(__file__).parent.parent / "docs" / "perfil_risco_investidor.md"


def _seed_config_rebalanceamento(session: Session) -> None:
    existing = session.exec(select(ConfigRebalanceamento)).first()
    if existing:
        return
    config = ConfigRebalanceamento(
        banda_absoluta_pp=5.0,
        banda_relativa_pct=25.0,
        piso_reais=500.0,
        piso_percentual=0.5,
        cadencia_dias=30,
    )
    session.add(config)
    logger.info("ConfigRebalanceamento semeada com padrões §8.2 do PLANO.")


def _seed_perfil_risco(session: Session) -> None:
    existing = session.exec(select(PerfilRisco)).first()
    if existing:
        return
    texto = ""
    if _PERFIL_RISCO_PATH.exists():
        texto = _PERFIL_RISCO_PATH.read_text(encoding="utf-8")
    perfil = PerfilRisco(texto=texto, observacoes_livres="")
    session.add(perfil)
    logger.info("PerfilRisco semeado a partir de perfil_risco_investidor.md.")


def _seed_alvos_classe(session: Session) -> None:
    existing = session.exec(select(AlvoClasse)).first()
    if existing:
        return
    # Alocação-alvo do perfil (system_prompt_consultor_otimizado_EXEMPLO_PREENCHIDO.md)
    alvos = [
        AlvoClasse(classe=ClasseAtivo.ACAO,    percentual=30.0),
        AlvoClasse(classe=ClasseAtivo.FII,     percentual=30.0),
        AlvoClasse(classe=ClasseAtivo.TESOURO, percentual=20.0),
        AlvoClasse(classe=ClasseAtivo.RF,      percentual=20.0),
        AlvoClasse(classe=ClasseAtivo.CAIXA,   percentual=0.0),
    ]
    for a in alvos:
        session.add(a)
    logger.info("AlvoClasse semeado: ACAO=30%%, FII=30%%, TESOURO=20%%, RF=20%%.")


def seed_all() -> None:
    with Session(engine) as session:
        _seed_config_rebalanceamento(session)
        _seed_perfil_risco(session)
        _seed_alvos_classe(session)
        session.commit()
