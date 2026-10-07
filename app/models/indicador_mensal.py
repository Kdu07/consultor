from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class IndicadorMensal(SQLModel, table=True):
    """
    Benchmark mensal já fechado (docs/PLANO_HISTORICO.md, Bloco 4) — CDI ou IPCA, em % no mês.

    Só entra mês completo: um mês fechado não muda mais, então fica em cache para sempre e
    o BCB só é consultado pelo que falta. CDI vem da série 12 (diária) composta na janela do
    extrato; IPCA, da série 433.
    """
    __table_args__ = (UniqueConstraint("serie", "mes"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    serie: str = Field(index=True)          # CDI | IPCA
    mes: str = Field(index=True)            # 'YYYY-MM'
    valor_pct: float
    fonte: str                              # sgs12 | sgs433
    obtido_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
