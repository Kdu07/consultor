"""
Stubs da Fase 5 — apenas modelos, zero lógica, zero tools.
Criados aqui para evitar migração de schema no futuro (PLANO §13, spec_persistencia_estrategia.md).
"""
from enum import Enum
from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class StatusPlano(str, Enum):
    ATIVO = "ativo"
    CUMPRIDO = "cumprido"
    CANCELADO = "cancelado"


class EstrategiaInvestimento(SQLModel, table=True):
    """Tese narrativa de investimento. Single-row ativa (version incrementa a cada alteração)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tese: str = Field(default="")
    version: int = Field(default=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanoFuturo(SQLModel, table=True):
    """Planos de compra/venda futuros vinculados à estratégia."""
    id: Optional[int] = Field(default=None, primary_key=True)
    estrategia_id: int = Field(foreign_key="estrategiainvestimento.id")
    descricao: str
    gatilho: Optional[str] = Field(default=None)
    horizonte: Optional[str] = Field(default=None)
    status: StatusPlano = Field(default=StatusPlano.ATIVO)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HistoricoEstrategia(SQLModel, table=True):
    """Log de auditoria de alterações na estratégia."""
    id: Optional[int] = Field(default=None, primary_key=True)
    estrategia_id: int = Field(foreign_key="estrategiainvestimento.id")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    origem: str = Field(default="usuário via chat")
    campo: str
    valor_anterior: Optional[str] = Field(default=None)
    valor_novo: Optional[str] = Field(default=None)
