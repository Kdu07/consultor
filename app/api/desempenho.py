"""
Desempenho da carteira (docs/PLANO_HISTORICO.md) — só leitura.

GET /desempenho             série mensal, janelas acumuladas (mês, ano, 12 meses, desde o
                            início), CDI e IPCA dos mesmos meses, renda passiva e pendências
GET /desempenho/composicao  resultado por classe e por ativo na janela, com a conferência
GET /desempenho/ativo       um papel mês a mês
GET /desempenho/export.csv  mensal ou por ativo, para o Excel (';', vírgula decimal, BOM)

Tudo calculado a partir dos extratos arquivados; nada aqui consulta a cotação do dia. O BCB
fora do ar não derruba a rota: `benchmarks.status` vira 'indisponivel' e o resto sai normal.
"""
import logging
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import Session

from .. import database
from ..tools.desempenho_servico import (
    FONTE,
    composicao_janela,
    csv_ativos,
    csv_mensal,
    desempenho_completo,
    historico_do_ativo,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/desempenho", tags=["desempenho"])

Janela = Literal["mes", "ano", "12m", "inicio"]


@router.get("")
async def obter_desempenho():
    with Session(database.engine) as session:
        dados = await desempenho_completo(session)
    return {
        **dados,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fonte": FONTE,
    }


@router.get("/composicao")
def obter_composicao(
    janela: Janela = "12m",
    mes: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
):
    with Session(database.engine) as session:
        return composicao_janela(session, janela, mes)


@router.get("/ativo")
def obter_ativo(chave: str, janela: Janela = "inicio"):
    with Session(database.engine) as session:
        dados = historico_do_ativo(session, chave, janela)
    if dados is None:
        raise HTTPException(status_code=404, detail="Esse papel não aparece nos extratos do período.")
    return dados


@router.get("/export.csv")
async def exportar_csv(tipo: Literal["mensal", "ativos"] = "mensal", janela: Janela = "inicio"):
    with Session(database.engine) as session:
        texto = await csv_mensal(session, janela) if tipo == "mensal" else csv_ativos(session, janela)
    nome = f"desempenho-{tipo}-{janela}-{date.today():%Y-%m-%d}.csv"
    return Response(
        content=texto.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
