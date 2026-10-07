"""
API de import do extrato — upload do XLSX do BTG (PLANO_XLSX §3, Bloco 2).

Este router NÃO grava posição nenhuma: ele parseia o arquivo e deixa o preview em
staging. A gravação continua exclusiva de gravar_posicoes, no turno seguinte ao "sim"
do usuário (guardrail 4 do projeto).

As rotas /extrato/historico expõem os meses já arquivados (ExtratoImportado), incluindo
proventos, movimentações e o razão da conta, que a tabela Posicao não guarda. A única escrita
aqui é apagar um mês do histórico — nunca uma posição (docs/PLANO_HISTORICO.md, Bloco 5).
"""
import json
import logging
from datetime import date

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import database
from ..models.extrato import ExtratoImportado
from ..tools import extrato_staging
from ..tools.btg_xlsx_parser import ExtratoParseError, mascarar_nome_arquivo, parse_btg_xlsx
from ..tools.desempenho import extrair_mes
from ..tools.extrato import montar_preview
from ..tools.extrato_arquivo import data_de_corte, excluir_mes
from ..tools.extrato_validacao import anexar_validacao
from ..tools.lancamentos import ROTULOS, classificar_mes
from ..tools.regras_lancamento import carregar_regras, carregar_regras_seguro

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/extrato", tags=["extrato"])

TAMANHO_MAXIMO = 5 * 1024 * 1024  # 5 MB — o extrato real tem ~25 KB


@router.post("/upload")
async def upload_extrato(arquivo: UploadFile = File(...)):
    """
    Recebe o XLSX do extrato, parseia e guarda o preview em memória.
    Retorna o mesmo preview que o agente verá em importar_extrato().
    """
    # O XLSX baixado do BTG se chama <número da conta>.xlsx: o nome é mascarado aqui, antes
    # de chegar ao staging, ao preview do agente, aos logs e ao histórico.
    nome = mascarar_nome_arquivo(arquivo.filename) or "extrato.xlsx"
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

    # Validação de invariantes (plano "Confiabilidade"): o bruto do staging é SEMPRE o
    # payload de anexar_validacao — é por payload["validacao"] que gravar_posicoes decide
    # bloquear. A Session é só para o V7 (encadeamento com o mês arquivado anterior);
    # banco indisponível não derruba o upload — o V7 fica de fora e o resto vale.
    try:
        with Session(database.engine) as session:
            bruto = anexar_validacao(extrato, session)
    except Exception as e:  # noqa: BLE001 — a validação nunca pode matar o upload
        logger.warning("upload_extrato: banco indisponível para o V7 (%s) — validando sem ele", e)
        bruto = anexar_validacao(extrato, None)

    preview = montar_preview(
        extrato, nome, regras=carregar_regras_seguro(), validacao=bruto["validacao"]
    )
    # O bruto vai junto para que gravar_posicoes possa arquivar o mês inteiro (inclui
    # as movimentações, que o preview não mostra). O XLSX é descartado ao sair daqui.
    extrato_staging.set_preview(preview, nome, bruto=bruto)

    logger.info(
        "upload_extrato: '%s' aceito — %d posicoes, ref=%s, checksum_ok=%s, validacao=%s",
        nome, preview["total_posicoes"], preview["data_referencia"],
        preview["checagem_totais"].get("ok"), bruto["validacao"]["veredito"],
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
    # Derivados do payload (docs/PLANO_HISTORICO.md, Bloco 5)
    mes: str | None = None
    patrimonio: float | None = None          # Total Bruto do Sumário (com trânsito)
    periodo_mensal: bool = True
    status: str | None = None                # o mesmo status do motor de desempenho
    tem_lancamentos: bool = False            # arquivo do parser v2, com o razão da conta
    lancamentos: int = 0
    nao_classificados: int = 0
    checagem_ok: bool | None = None
    checagem_conta_ok: bool | None = None
    # Veredito do validador de invariantes (payload["validacao"], parser v3).
    # None/0 em payloads v1/v2, anteriores ao validador — a UI orienta reenviar.
    validacao_veredito: str | None = None
    validacao_erros: int = 0
    protegido: bool = False                  # é o mês do corte: não pode ser excluído


def _resumo(e: ExtratoImportado, payload: dict | None = None, regras=(), corte: date | None = None) -> ExtratoResumo:
    resumo = ExtratoResumo(
        id=e.id,
        data_referencia=e.data_referencia,
        arquivo=e.arquivo,
        total_posicoes=e.total_posicoes,
        total_valor_mercado=e.total_valor_mercado,
        proventos_total=e.proventos_total,
        proventos_quantidade=e.proventos_quantidade,
        importado_em=e.importado_em.isoformat(),
        atualizado_em=e.atualizado_em.isoformat(),
        protegido=corte is not None and e.data_referencia == corte,
    )
    if payload is not None:
        mes = extrair_mes(e.data_referencia, payload, regras)
        checagem = payload.get("checagem") or {}
        resumo.mes = mes["mes"]
        resumo.patrimonio = mes["patrimonio_fim"]
        resumo.periodo_mensal = mes["status"] != "periodo_parcial"
        resumo.status = mes["status"]
        resumo.tem_lancamentos = mes["versao_parser"] >= 2
        resumo.lancamentos = len(payload.get("lancamentos_conta") or [])
        resumo.nao_classificados = mes["nao_classificados"]
        resumo.checagem_ok = checagem.get("ok")
        resumo.checagem_conta_ok = (checagem.get("conta_corrente") or {}).get("ok")
        validacao = payload.get("validacao") or {}
        resumo.validacao_veredito = validacao.get("veredito")
        resumo.validacao_erros = len(validacao.get("erros") or [])
    return resumo


def _payload(registro: ExtratoImportado) -> dict:
    try:
        return json.loads(registro.payload_json)
    except json.JSONDecodeError:
        logger.error("historico: payload ilegivel no extrato id=%d", registro.id)
        raise HTTPException(status_code=500, detail="Payload arquivado está corrompido.")


def _registro(session: Session, data_referencia: date) -> ExtratoImportado:
    registro = session.exec(
        select(ExtratoImportado).where(ExtratoImportado.data_referencia == data_referencia)
    ).first()
    if registro is None:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum extrato arquivado com data de referência {data_referencia}.",
        )
    return registro


@router.get("/historico", response_model=list[ExtratoResumo])
async def listar_historico():
    """Meses já importados, do mais recente para o mais antigo."""
    with Session(database.engine) as session:
        registros = session.exec(
            select(ExtratoImportado).order_by(ExtratoImportado.data_referencia.desc())
        ).all()
        regras = carregar_regras(session)
        corte = data_de_corte(session)
        saida = []
        for e in registros:
            try:
                payload = json.loads(e.payload_json)
            except json.JSONDecodeError:
                logger.error("historico: payload ilegivel no extrato id=%d", e.id)
                payload = None
            saida.append(_resumo(e, payload, regras, corte))
    return saida


@router.get("/historico/{data_referencia}/lancamentos")
async def lancamentos_do_mes(data_referencia: date):
    """Razão da conta corrente do mês, classificado com as regras de agora."""
    with Session(database.engine) as session:
        registro = _registro(session, data_referencia)
        regras = carregar_regras(session)
    payload = _payload(registro)
    versao = int(payload.get("versao_parser") or 1)
    classificados = classificar_mes(
        data_referencia.isoformat(), payload.get("lancamentos_conta") or [], regras
    )
    for c in classificados:
        c["rotulo"] = ROTULOS.get(c["tipo"], c["tipo"])
    return {
        "data_referencia": data_referencia.isoformat(),
        "tem_lancamentos": versao >= 2,
        "saldo_inicial": payload.get("saldo_inicial_conta"),
        "checagem": (payload.get("checagem") or {}).get("conta_corrente"),
        "lancamentos": classificados,
    }


@router.get("/historico/{data_referencia}")
async def obter_historico(data_referencia: date):
    """Extrato completo de um mês (YYYY-MM-DD), como o parser o leu."""
    with Session(database.engine) as session:
        registro = _registro(session, data_referencia)
        regras = carregar_regras(session)
        corte = data_de_corte(session)
    payload = _payload(registro)
    return {**_resumo(registro, payload, regras, corte).model_dump(mode="json"), "extrato": payload}


@router.delete("/historico/{data_referencia}", status_code=204)
async def excluir_historico(data_referencia: date):
    """
    Apaga um mês do histórico. Não desfaz nada na carteira. O mês do corte (o que a
    carteira reflete, ou o arquivo mais recente se for mais novo) não pode ser apagado:
    é ele que diz quais imports entram só como histórico.
    """
    with Session(database.engine) as session:
        _registro(session, data_referencia)
        if data_referencia == data_de_corte(session):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Este é o mês que a carteira reflete hoje e não pode ser excluído. "
                    "Importe um extrato mais novo antes, se quiser apagá-lo."
                ),
            )
        excluir_mes(session, data_referencia)
        session.commit()
