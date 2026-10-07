"""
Extratos em lote e regras de classificação (docs/PLANO_HISTORICO.md, Bloco 5).

POST   /extrato/lote                    vários XLSX → avaliação de cada mês (nada é gravado)
POST   /extrato/lote/{id}/confirmar     arquiva os meses escolhidos — só histórico
DELETE /extrato/lote/{id}               descarta o lote
GET    /extrato/regras                  regras de classificação do dono
POST   /extrato/regras                  cria ou corrige uma regra
DELETE /extrato/regras/{id}
GET    /extrato/comparar?de=&ate=       dois fechamentos lado a lado (Bloco 9)

Exceção consciente ao guardrail 4 ("gravação só depois do 'sim' no chat"): o lote é
confirmado na tela. Ele só arquiva meses que NÃO mexem na carteira (anteriores à data que
ela reflete, ou o próprio mês dela com as mesmas posições) — e a confirmação é um clique
explícito do dono. Mês mais novo que a carteira continua indo pelo chat.
"""
import json
import logging
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import database
from ..models.extrato import ExtratoImportado
from ..tools import extrato_lote
from ..tools.btg_xlsx_parser import ExtratoParseError, mascarar_nome_arquivo, parse_btg_xlsx
from ..tools.composicao import comparar
from ..tools.desempenho import periodo_entre
from ..tools.desempenho_servico import carregar_meses, meses_calculados
from ..tools.extrato_arquivo import data_de_corte
from ..tools.lancamentos import ROTULOS, classificar_mes
from ..tools.regras_lancamento import (
    RegraInvalida,
    carregar_regras,
    criar_ou_atualizar,
    excluir,
    listar,
)
from .extrato import TAMANHO_MAXIMO

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/extrato", tags=["extrato"])


# ---------------------------------------------------------------------------
# Lote
# ---------------------------------------------------------------------------

@router.post("/lote")
async def enviar_lote(arquivos: list[UploadFile] = File(...)):
    if not arquivos:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")
    if len(arquivos) > extrato_lote.MAX_ARQUIVOS:
        raise HTTPException(
            status_code=400,
            detail=f"No máximo {extrato_lote.MAX_ARQUIVOS} extratos por lote.",
        )

    recebidos: list[tuple[str, object, Optional[str]]] = []
    for arquivo in arquivos:
        nome = mascarar_nome_arquivo(arquivo.filename) or "extrato.xlsx"
        if not nome.lower().endswith(".xlsx"):
            recebidos.append((nome, None, "Só extratos em .xlsx são aceitos."))
            continue
        conteudo = await arquivo.read()
        if not conteudo:
            recebidos.append((nome, None, "Arquivo vazio."))
            continue
        if len(conteudo) > TAMANHO_MAXIMO:
            recebidos.append((nome, None, "Arquivo grande demais — não parece um extrato."))
            continue
        try:
            recebidos.append((nome, parse_btg_xlsx(conteudo), None))
        except ExtratoParseError as e:
            recebidos.append((nome, None, str(e)))
        except Exception as e:  # noqa: BLE001 — um arquivo ruim não derruba o lote
            logger.error("lote: falha inesperada ao parsear '%s': %s", nome, e)
            recebidos.append((nome, None, f"Não consegui ler o extrato: {e}"))

    with Session(database.engine) as session:
        regras = carregar_regras(session)
        itens = extrato_lote.avaliar(session, recebidos, regras)
        corte = data_de_corte(session)

    lote = extrato_lote.guardar(itens)
    logger.info("lote %s: %d arquivo(s) avaliados", lote["id"], len(itens))
    return extrato_lote.para_resposta(lote, corte)


class ConfirmarLote(BaseModel):
    datas: list[date]


@router.post("/lote/{lote_id}/confirmar")
def confirmar_lote(lote_id: str, corpo: ConfirmarLote):
    lote = extrato_lote.obter(lote_id)
    if lote is None:
        raise HTTPException(
            status_code=404,
            detail="O lote expirou ou não existe mais — envie os arquivos de novo.",
        )
    with Session(database.engine) as session:
        resultado = extrato_lote.confirmar(
            session, lote, [d.isoformat() for d in corpo.datas], carregar_regras(session)
        )
    extrato_lote.descartar(lote_id)
    return resultado


@router.delete("/lote/{lote_id}", status_code=204)
def descartar_lote(lote_id: str):
    extrato_lote.descartar(lote_id)


# ---------------------------------------------------------------------------
# Regras de classificação
# ---------------------------------------------------------------------------

class RegraEntrada(BaseModel):
    tipo: str
    escopo: Literal["texto", "linha", "ativo_mes"] = "texto"
    modo: Literal["exato", "prefixo", "contem"] = "prefixo"
    padrao: str = ""
    sinal: Optional[Literal["credito", "debito"]] = None
    data_referencia: Optional[date] = None
    seq: Optional[int] = None
    chave: Optional[str] = None      # escopo ativo_mes: a chave_externa do papel


def _regra_saida(r) -> dict:
    return {
        "id": r.id,
        "escopo": r.escopo,
        "modo": r.modo,
        "padrao": r.padrao,
        "sinal": r.sinal,
        "data_referencia": r.data_referencia.isoformat() if r.data_referencia else None,
        "seq": r.seq,
        "tipo": r.tipo,
        "rotulo": ROTULOS.get(r.tipo, r.tipo),
        "criado_em": r.criado_em.isoformat(),
        "atualizado_em": r.atualizado_em.isoformat(),
    }


@router.get("/regras")
def listar_regras():
    with Session(database.engine) as session:
        return [_regra_saida(r) for r in listar(session)]


@router.post("/regras", status_code=201)
def criar_regra(corpo: RegraEntrada):
    with Session(database.engine) as session:
        lancamento = None
        if corpo.escopo == "linha":
            if corpo.data_referencia is None or corpo.seq is None:
                raise HTTPException(status_code=400, detail="Regra de linha precisa do mês e da linha.")
            lancamento = _lancamento_arquivado(session, corpo.data_referencia, corpo.seq)
        try:
            regra, nova = criar_ou_atualizar(
                session,
                tipo=corpo.tipo,
                escopo=corpo.escopo,
                modo=corpo.modo,
                padrao=(corpo.chave or "") if corpo.escopo == "ativo_mes" else corpo.padrao,
                sinal=corpo.sinal,
                data_referencia=corpo.data_referencia,
                seq=corpo.seq,
                lancamento=lancamento,
            )
        except RegraInvalida as e:
            raise HTTPException(status_code=400, detail=str(e))
        session.commit()
        session.refresh(regra)
        saida = _regra_saida(regra)
        afetados = _afetados(session, regra.id)
    return {"regra": saida, "nova": nova, "afetados": afetados}


@router.delete("/regras/{regra_id}", status_code=204)
def excluir_regra(regra_id: int):
    with Session(database.engine) as session:
        if not excluir(session, regra_id):
            raise HTTPException(status_code=404, detail="Regra não encontrada.")
        session.commit()


def _lancamento_arquivado(session: Session, data_ref: date, seq: int) -> dict:
    registro = session.exec(
        select(ExtratoImportado).where(ExtratoImportado.data_referencia == data_ref)
    ).first()
    if registro is None:
        raise HTTPException(status_code=404, detail=f"Nenhum extrato arquivado em {data_ref}.")
    try:
        lancamentos = json.loads(registro.payload_json).get("lancamentos_conta") or []
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Payload arquivado está corrompido.")
    for lanc in lancamentos:
        if lanc.get("seq") == seq:
            return lanc
    raise HTTPException(status_code=404, detail=f"Lançamento {seq} não existe em {data_ref}.")


def _afetados(session: Session, regra_id: int) -> dict:
    """Quantos meses e lançamentos arquivados passam a ser classificados pela regra."""
    regras = carregar_regras(session)
    meses = 0
    lancamentos = 0
    for arquivo in carregar_meses(session):
        payload = arquivo["payload"]
        classificados = classificar_mes(
            arquivo["data_referencia"], payload.get("lancamentos_conta") or [], regras
        )
        n = sum(1 for c in classificados if c["regra_id"] == regra_id)
        if n:
            meses += 1
            lancamentos += n
    return {"meses": meses, "lancamentos": lancamentos}


# ---------------------------------------------------------------------------
# Comparar dois fechamentos
# ---------------------------------------------------------------------------

@router.get("/comparar")
def comparar_meses(de: date, ate: date):
    """Posições que entraram, saíram e mudaram, alocação por classe e o período entre as datas."""
    if de >= ate:
        raise HTTPException(status_code=400, detail="A primeira data tem de ser anterior à segunda.")
    with Session(database.engine) as session:
        registros = {
            r.data_referencia: r
            for r in session.exec(
                select(ExtratoImportado).where(ExtratoImportado.data_referencia.in_((de, ate)))
            ).all()
        }
        for d in (de, ate):
            if d not in registros:
                raise HTTPException(
                    status_code=404, detail=f"Nenhum extrato arquivado em {d:%d/%m/%Y}."
                )
        try:
            payloads = {d: json.loads(registros[d].payload_json) for d in (de, ate)}
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Payload arquivado está corrompido.")
        meses, _ = meses_calculados(session)
    return {
        "de": de.isoformat(),
        "ate": ate.isoformat(),
        **comparar(payloads[de], payloads[ate]),
        "periodo": periodo_entre(meses, de, ate),
    }
