"""
API de import do extrato — upload do XLSX do BTG (PLANO_XLSX §3, Bloco 2).

Este router NÃO grava posição nenhuma: ele parseia o arquivo e deixa o preview em
staging. A gravação continua exclusiva de gravar_posicoes, no turno seguinte ao "sim"
do usuário (guardrail 4 do projeto).

As rotas /extrato/historico são só leitura: expõem os meses já arquivados por
gravar_posicoes (ExtratoImportado), incluindo proventos e movimentações, que a tabela
Posicao não guarda.
"""
import json
import logging
from datetime import date

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from ..database import engine
from ..models.extrato import ExtratoImportado
from ..tools import extrato_staging
from ..tools.btg_xlsx_parser import ExtratoParseError, parse_btg_xlsx
from ..tools.extrato import montar_preview

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/extrato", tags=["extrato"])

TAMANHO_MAXIMO = 5 * 1024 * 1024  # 5 MB — o extrato real tem ~25 KB


@router.post("/upload")
async def upload_extrato(arquivo: UploadFile = File(...)):
    """
    Recebe o XLSX do extrato, parseia e guarda o preview em memória.
    Retorna o mesmo preview que o agente verá em importar_extrato().
    """
    nome = arquivo.filename or "extrato.xlsx"
    if not nome.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Envie o extrato em .xlsx (Excel). "
                "Formatos antigos (.xls) e PDF não são aceitos."
            ),
        )

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(
            status_code=400,
            detail=f"Arquivo maior que {TAMANHO_MAXIMO // (1024 * 1024)} MB — não parece um extrato.",
        )

    try:
        extrato = parse_btg_xlsx(conteudo)
    except ExtratoParseError as e:
        logger.warning("upload_extrato: arquivo rejeitado ('%s'): %s", nome, e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("upload_extrato: falha inesperada ao parsear '%s': %s", nome, e)
        raise HTTPException(status_code=400, detail=f"Não consegui ler o extrato: {e}")

    preview = montar_preview(extrato, nome)
    # O bruto vai junto para que gravar_posicoes possa arquivar o mês inteiro (inclui
    # as movimentações, que o preview não mostra). O XLSX é descartado ao sair daqui.
    extrato_staging.set_preview(preview, nome, bruto=extrato.to_dict())

    logger.info(
        "upload_extrato: '%s' aceito — %d posicoes, ref=%s, checksum_ok=%s",
        nome, preview["total_posicoes"], preview["data_referencia"],
        preview["checagem_totais"].get("ok"),
    )
    return preview


@router.get("/preview")
async def obter_preview():
    """Preview do último extrato enviado (404 se não houver)."""
    estado = extrato_staging.get()
    if not estado:
        raise HTTPException(status_code=404, detail="Nenhum extrato enviado nesta sessão.")
    return {**estado["preview"], "recebido_em": estado["recebido_em"]}


@router.delete("/preview", status_code=204)
async def descartar_preview():
    """Descarta o preview em staging."""
    extrato_staging.clear()


# ---------------------------------------------------------------------------
# Histórico — meses já importados
# ---------------------------------------------------------------------------

class ExtratoResumo(BaseModel):
    """Uma linha do histórico. Sem o payload, que é grande."""
    id: int
    data_referencia: date
    arquivo: str | None
    total_posicoes: int
    total_valor_mercado: float
    proventos_total: float
    proventos_quantidade: int
    importado_em: str
    atualizado_em: str


def _resumo(e: ExtratoImportado) -> ExtratoResumo:
    return ExtratoResumo(
        id=e.id,
        data_referencia=e.data_referencia,
        arquivo=e.arquivo,
        total_posicoes=e.total_posicoes,
        total_valor_mercado=e.total_valor_mercado,
        proventos_total=e.proventos_total,
        proventos_quantidade=e.proventos_quantidade,
        importado_em=e.importado_em.isoformat(),
        atualizado_em=e.atualizado_em.isoformat(),
    )


@router.get("/historico", response_model=list[ExtratoResumo])
async def listar_historico():
    """Meses já importados, do mais recente para o mais antigo."""
    with Session(engine) as session:
        registros = session.exec(
            select(ExtratoImportado).order_by(ExtratoImportado.data_referencia.desc())
        ).all()
    return [_resumo(e) for e in registros]


@router.get("/historico/{data_referencia}")
async def obter_historico(data_referencia: date):
    """Extrato completo de um mês (YYYY-MM-DD), como o parser o leu."""
    with Session(engine) as session:
        registro = session.exec(
            select(ExtratoImportado).where(ExtratoImportado.data_referencia == data_referencia)
        ).first()

    if registro is None:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum extrato arquivado com data de referência {data_referencia}.",
        )

    try:
        payload = json.loads(registro.payload_json)
    except json.JSONDecodeError:
        logger.error("historico: payload ilegivel no extrato id=%d", registro.id)
        raise HTTPException(status_code=500, detail="Payload arquivado está corrompido.")

    return {**_resumo(registro).model_dump(mode="json"), "extrato": payload}
