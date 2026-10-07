from typing import Optional
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field


class ReferenciaCarteira(SQLModel, table=True):
    """
    Data do extrato que a carteira atual reflete. Uma linha só.

    É a data de corte do import (docs/PLANO_HISTORICO.md, decisão técnica 1): extrato
    anterior a ela entra só no histórico, sem tocar em Posicao. Antes dela existir, o corte
    era só o extrato arquivado mais recente — e um banco sem nenhum arquivado (produção em
    10/2026) deixava um import antigo reconciliar a carteira para trás.

    Só o import de extrato no modo normal atualiza esta linha (origem 'import'). No boot,
    se ela não existe e há posições vindas de extrato, é semeada com o maior `as_of` delas
    (origem 'semente'). Edição manual de posição não a move: o `as_of` dessas edições vem de
    quem chama.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    data_referencia: date
    origem: str = Field(default="import")
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
