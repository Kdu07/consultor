"""
API de import do extrato — upload do XLSX do BTG (PLANO_XLSX §3, Bloco 2).

Este router NÃO grava posição nenhuma: ele parseia o arquivo e deixa o preview em
staging. A gravação continua exclusiva de gravar_posicoes, no turno seguinte ao "sim"
do usuário (guardrail 4 do projeto).
"""
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

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
    extrato_staging.set_preview(preview, nome)

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
