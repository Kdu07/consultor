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

    # Identidade do papel entre extratos ('B3:BBAS3', 'TD:LFT:2031-03-01'). É por ela que
    # o upsert do import casa a posição — o `nome` do extrato muda de mês para mês.
    # Nulo em posição criada à mão e nas linhas anteriores à migração; nesses casos o
    # upsert cai em ticker/nome e preenche a chave no primeiro import que casar.
    # Formato em app/tools/btg_xlsx_parser.py, seção "Identidade do papel entre extratos".
    chave_externa: Optional[str] = Field(default=None, index=True)

    # quantidade / valor
    quantidade: float = Field(default=0.0)
    preco_medio: Optional[float] = Field(default=None)  # custo médio de aquisição
    valor_mercado: Optional[float] = Field(default=None)  # último valor calculado

    # renda fixa (Tesouro e RF privada) — vêm do extrato XLSX
    vencimento: Optional[datetime] = Field(default=None)
    taxa_contratada: Optional[str] = Field(default=None)  # ex.: "IPCA + 7,62%", "SELIC + 0,10%"

    # proveniência do dado de valor
    source: str = Field(default="extrato")  # brapi | yfinance | tesouro | extrato
    as_of: Optional[datetime] = Field(default=None)

    # controle
    ativo: bool = Field(default=True)
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notas: Optional[str] = Field(default=None)
