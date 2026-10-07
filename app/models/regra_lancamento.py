from typing import Optional
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field


class RegraLancamento(SQLModel, table=True):
    """
    Classificação de lançamento do razão escolhida pelo dono (docs/PLANO_HISTORICO.md, §3.2).

    Aplicada na hora do cálculo, nunca gravada no extrato: por isso vale retroativamente
    para todos os meses arquivados. Três escopos:
      - texto:     todas as descrições que casam com `padrao` (exato | prefixo | contém),
                   opcionalmente só créditos ou só débitos (`sinal`);
      - linha:     uma linha de um mês (`data_referencia` + `seq`), enquanto a `impressao`
                   dela não mudar — reimportar o mês com outro conteúdo a invalida;
      - ativo_mes: evento de um papel num mês (`padrao` = chave_externa), para mudança de
                   quantidade sem negociação (desdobramento, transferência de custódia).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    escopo: str = Field(default="texto", index=True)
    modo: str = Field(default="prefixo")
    padrao: str = Field(default="", index=True)
    sinal: Optional[str] = Field(default=None)
    data_referencia: Optional[date] = Field(default=None, index=True)
    seq: Optional[int] = Field(default=None)
    impressao: Optional[str] = Field(default=None)
    tipo: str
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
