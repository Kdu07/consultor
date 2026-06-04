from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class QuoteCache(SQLModel, table=True):
    """Cache de cotações com TTL configurável (padrão 15 min)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    price: float
    source: str          # brapi | yfinance | tesouro
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Optional[str] = Field(default=None)  # JSON bruto da resposta, para debug
