from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class PerfilRisco(SQLModel, table=True):
    """
    Perfil de risco do investidor. Single-row.
    O campo `texto` é o bloco markdown que alimenta o {perfil_risco} do system prompt.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    texto: str = Field(default="")           # bloco markdown completo do perfil
    observacoes_livres: str = Field(default="")  # slot {observacoes_livres} do system prompt
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
