"""
Regras de classificação do dono — persistência (docs/PLANO_HISTORICO.md, Bloco 2).

O classificador (lancamentos.py) é puro; aqui fica o vaivém com o banco. Upsert pela
unicidade lógica de cada escopo, para que reclassificar a mesma coisa corrija a regra em
vez de empilhar outra:
  - texto:     (modo, padrao, sinal)
  - linha:     (data_referencia, seq)
  - ativo_mes: (data_referencia, padrao)

O banco é acessado como `database.engine` na hora da chamada, não importado no carregamento
do módulo: assim os testes que trocam o engine de app.database valem aqui sem patch extra.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from .. import database
from ..models.regra_lancamento import RegraLancamento
from .lancamentos import (  # noqa: F401 — as constantes de ativo_mes são reexportadas
    APORTE_EM_ATIVOS,
    EVENTO_SOCIETARIO,
    MODOS,
    RESGATE_EM_ATIVOS,
    SINAIS,
    TIPOS,
    TIPOS_ATIVO_MES,
    Regra,
    chave_de_texto,
    impressao_linha,
)

logger = logging.getLogger(__name__)

ESCOPOS = ("texto", "linha", "ativo_mes")


class RegraInvalida(ValueError):
    """Dados de regra que não fazem sentido — a rota devolve 400 com a mensagem."""


def para_regra(r: RegraLancamento) -> Regra:
    return Regra(
        tipo=r.tipo,
        escopo=r.escopo,
        modo=r.modo,
        padrao=r.padrao,
        sinal=r.sinal,
        data_referencia=r.data_referencia.isoformat() if r.data_referencia else None,
        seq=r.seq,
        impressao=r.impressao,
        id=r.id,
    )


def carregar_regras(session: Session) -> list[Regra]:
    return [para_regra(r) for r in session.exec(select(RegraLancamento)).all()]


def carregar_regras_seguro() -> list[Regra]:
    """Regras do dono, ou [] se o banco ainda não tem a tabela (testes sem schema)."""
    try:
        with Session(database.engine) as session:
            return carregar_regras(session)
    except OperationalError as e:
        logger.warning("regras de lancamento indisponiveis: %s", e.__class__.__name__)
        return []


def listar(session: Session) -> list[RegraLancamento]:
    return list(session.exec(
        select(RegraLancamento).order_by(RegraLancamento.escopo, RegraLancamento.padrao)
    ).all())


def criar_ou_atualizar(
    session: Session,
    *,
    tipo: str,
    escopo: str = "texto",
    modo: str = "prefixo",
    padrao: str = "",
    sinal: Optional[str] = None,
    data_referencia: Optional[date] = None,
    seq: Optional[int] = None,
    lancamento: Optional[dict] = None,
) -> tuple[RegraLancamento, bool]:
    """
    Grava a regra (sem commit — quem chama decide a transação). Retorna (regra, era_nova).
    Na regra de linha, `lancamento` é a linha arquivada: dela sai a impressão que amarra a
    regra ao conteúdo atual do mês.
    """
    if escopo not in ESCOPOS:
        raise RegraInvalida(f"Escopo desconhecido: {escopo}.")

    impressao: Optional[str] = None
    if escopo == "texto":
        if tipo not in TIPOS:
            raise RegraInvalida(f"Tipo desconhecido: {tipo}.")
        if modo not in MODOS:
            raise RegraInvalida(f"Modo desconhecido: {modo}.")
        if sinal is not None and sinal not in SINAIS:
            raise RegraInvalida(f"Sinal desconhecido: {sinal}.")
        padrao = chave_de_texto(padrao)
        if not padrao:
            raise RegraInvalida("A regra precisa de um texto para casar.")
        data_referencia, seq = None, None
        consulta = (
            select(RegraLancamento)
            .where(RegraLancamento.escopo == "texto")
            .where(RegraLancamento.modo == modo)
            .where(RegraLancamento.padrao == padrao)
            .where(RegraLancamento.sinal == sinal if sinal else RegraLancamento.sinal.is_(None))
        )
    elif escopo == "linha":
        if tipo not in TIPOS:
            raise RegraInvalida(f"Tipo desconhecido: {tipo}.")
        if data_referencia is None or seq is None or lancamento is None:
            raise RegraInvalida("Regra de linha precisa do mês e da linha.")
        impressao = impressao_linha(data_referencia.isoformat(), lancamento)
        modo, padrao, sinal = "exato", "", None
        consulta = (
            select(RegraLancamento)
            .where(RegraLancamento.escopo == "linha")
            .where(RegraLancamento.data_referencia == data_referencia)
            .where(RegraLancamento.seq == seq)
        )
    else:  # ativo_mes
        if tipo not in TIPOS_ATIVO_MES:
            raise RegraInvalida(f"Tipo de evento desconhecido: {tipo}.")
        if data_referencia is None or not padrao:
            raise RegraInvalida("Regra de ativo precisa do mês e da chave do papel.")
        modo, sinal, seq = "exato", None, None
        consulta = (
            select(RegraLancamento)
            .where(RegraLancamento.escopo == "ativo_mes")
            .where(RegraLancamento.data_referencia == data_referencia)
            .where(RegraLancamento.padrao == padrao)
        )

    agora = datetime.now(timezone.utc)
    regra = session.exec(consulta).first()
    era_nova = regra is None
    if regra is None:
        regra = RegraLancamento(
            escopo=escopo, modo=modo, padrao=padrao, sinal=sinal,
            data_referencia=data_referencia, seq=seq, tipo=tipo, criado_em=agora,
        )
    regra.tipo = tipo
    regra.impressao = impressao
    regra.atualizado_em = agora
    session.add(regra)
    session.flush()
    logger.info("regra de lancamento %s: id=%s escopo=%s tipo=%s",
                "criada" if era_nova else "atualizada", regra.id, escopo, tipo)
    return regra, era_nova


def excluir(session: Session, regra_id: int) -> bool:
    regra = session.get(RegraLancamento, regra_id)
    if regra is None:
        return False
    session.delete(regra)
    return True


def excluir_do_mes(session: Session, data_referencia: date) -> int:
    """Regras de linha e de ativo presas a um mês — somem junto com o mês excluído."""
    regras = session.exec(
        select(RegraLancamento)
        .where(RegraLancamento.data_referencia == data_referencia)
        .where(RegraLancamento.escopo.in_(("linha", "ativo_mes")))
    ).all()
    for r in regras:
        session.delete(r)
    return len(regras)
