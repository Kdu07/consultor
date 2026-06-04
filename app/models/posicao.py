from enum import Enum
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class ClasseAtivo(str, Enum):
    ACAO = "ACAO"
    FII = "FII"
    ETF = "ETF"
    BDR = "BDR"
    RF = "RF"           # renda fixa privada (CDB, LCI, LCA) — valor do extrato
    TESOURO = "TESOURO" # Tesouro Direto — preço diário oficial
    FUNDO = "FUNDO"     # fundos sem cotação pública — valor do extrato
    CAIXA = "CAIXA"


class Posicao(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # identificação
    ticker: Optional[str] = Field(default=None, index=True)  # nullable (ex.: CDB sem ticker)
    nome: str
    classe: ClasseAtivo

    # quantidade / valor
    quantidade: float = Field(default=0.0)
    preco_medio: Optional[float] = Field(default=None)  # custo médio de aquisição
    valor_mercado: Optional[float] = Field(default=None)  # último valor calculado

    # proveniência do dado de valor
    source: str = Field(default="extrato")  # brapi | yfinance | tesouro | extrato
    as_of: Optional[datetime] = Field(default=None)

    # controle
    ativo: bool = Field(default=True)
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notas: Optional[str] = Field(default=None)
