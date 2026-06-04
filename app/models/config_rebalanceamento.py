from typing import Optional
from sqlmodel import SQLModel, Field


class ConfigRebalanceamento(SQLModel, table=True):
    """
    Parâmetros da regra 5/25 (Swedroe). Single-row — há sempre exatamente 1 registro.
    Semeado com os padrões do PLANO §8.2.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    # Regra 5/25
    banda_absoluta_pp: float = Field(default=5.0)    # p.p. absolutos
    banda_relativa_pct: float = Field(default=25.0)  # % relativo ao alvo

    # Piso de irrelevância — não movimentar abaixo deste valor
    piso_reais: float = Field(default=500.0)         # R$ mínimo
    piso_percentual: float = Field(default=0.5)      # % mínimo da carteira

    # Cadência
    cadencia_dias: int = Field(default=30)           # avaliar 1x/mês
