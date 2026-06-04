from typing import Optional
from sqlmodel import SQLModel, Field
from .posicao import ClasseAtivo


class AlvoClasse(SQLModel, table=True):
    """Percentual-alvo por classe de ativo. Soma deve ser 100%."""
    id: Optional[int] = Field(default=None, primary_key=True)
    classe: ClasseAtivo = Field(unique=True, index=True)
    percentual: float  # ex.: 30.0 para 30%
    notas: Optional[str] = Field(default=None)


class AlvoAtivo(SQLModel, table=True):
    """Percentual-alvo por ativo individual. Soma deve ser 100%."""
    id: Optional[int] = Field(default=None, primary_key=True)
    identificador: str = Field(unique=True, index=True)  # ticker ou nome do ativo
    percentual: float
    notas: Optional[str] = Field(default=None)
