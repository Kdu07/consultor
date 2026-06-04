from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable


@dataclass
class Quote:
    """Cotação padronizada — todo número carrega source e as_of (PLANO §6.3)."""
    ticker: str
    price: float
    source: str              # brapi | yfinance | tesouro | extrato
    as_of: datetime = field(default_factory=datetime.utcnow)
    is_cached: bool = False
    # Campos opcionais enriquecidos (disponíveis via dados_ativo)
    variacao_pct: Optional[float] = None  # variação no dia (%)
    pl: Optional[float] = None            # P/L
    setor: Optional[str] = None
    nome: Optional[str] = None


@runtime_checkable
class PriceProvider(Protocol):
    """Contrato único de acesso a cotações. Nunca lança exceção — retorna None em falha."""

    def quote(self, ticker: str) -> Optional[Quote]:
        """Retorna Quote ou None (nunca levanta exceção para o chamador)."""
        ...

    def enrich(self, ticker: str) -> Optional[Quote]:
        """Retorna Quote com campos opcionais preenchidos (variacao_pct, pl, setor, nome)."""
        ...
