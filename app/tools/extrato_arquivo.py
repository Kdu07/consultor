"""
Arquivamento do extrato importado — o histórico que a tabela Posicao não guarda.

Por que existe (ver docstring de ExtratoImportado): `gravar_posicoes` faz upsert
destrutivo. Quantidade e valor do mês anterior são sobrescritos, e proventos,
movimentações, aluguel e valores em trânsito viviam só no preview em memória, que é
descartado logo depois. Sem isto, importar setembro apaga a foto de agosto.

A escrita é ExtratoImportado — o extrato inteiro do parser, como veio —, idempotente por
`data_referencia`: reimportar o mesmo mês é rotina (o usuário corrige um arquivo, reenvia
o mesmo XLSX), então o mês é corrigido no lugar, nunca duplicado. É dele que saem as
séries do Histórico (docs/PLANO_HISTORICO.md). O SnapshotMensal que esta camada gravava
foi aposentado: a série de patrimônio sai do próprio extrato arquivado, e a tabela ficou
só com os snapshots antigos, como legado.

As funções recebem a Session de quem chama e NÃO fazem commit: o arquivamento entra na
mesma transação da gravação das posições. Ou o mês inteiro é gravado — posições e
histórico — ou nada é.
"""
import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, select

from ..models.extrato import ExtratoImportado
from ..models.posicao import Posicao
from ..models.referencia_carteira import ReferenciaCarteira
from ..models.snapshot_mensal import SnapshotMensal
from .btg_xlsx_parser import mascarar_nome_arquivo
from .regras_lancamento import excluir_do_mes

logger = logging.getLogger(__name__)


def parse_data_referencia(valor) -> date | None:
    """'YYYY-MM-DD' (formato do parser) → date. None se ausente ou ilegível."""
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        logger.warning("data_referencia ilegivel no extrato: %r", valor)
        return None


def extrato_mais_recente(session: Session) -> date | None:
    """Maior data de referência já arquivada, ou None se o histórico está vazio."""
    return session.exec(
        select(ExtratoImportado.data_referencia)
        .order_by(ExtratoImportado.data_referencia.desc())
        .limit(1)
    ).first()


# ---------------------------------------------------------------------------
# Data de corte — o que um import pode tocar
# ---------------------------------------------------------------------------
#
# Extrato com data anterior ao corte entra só no histórico (arquivo + snapshot) e não
# mexe em Posicao. O corte é o mais novo entre o extrato arquivado mais recente e a data
# que a carteira reflete (ReferenciaCarteira). Só olhar o arquivo não basta: um banco sem
# nada arquivado — produção em 10/2026, com a carteira em 2026-08-10 — deixaria um
# extrato de junho reconciliar a carteira para trás.

def as_of_das_posicoes(session: Session) -> date | None:
    """Maior as_of entre as posições ativas vindas de extrato (as que têm chave_externa)."""
    maior = session.exec(
        select(func.max(Posicao.as_of))
        .where(Posicao.ativo == True)  # noqa: E712
        .where(Posicao.chave_externa.is_not(None))
    ).first()
    if maior is None:
        return None
    if isinstance(maior, datetime):
        return maior.date()
    if isinstance(maior, date):
        return maior
    return parse_data_referencia(maior)


def referencia_da_carteira(session: Session) -> date | None:
    """
    Data do extrato que a carteira reflete. Sem a linha de ReferenciaCarteira (banco que
    ainda não passou pela semente do boot), cai no as_of das posições vindas de extrato.
    """
    registro = session.exec(select(ReferenciaCarteira)).first()
    if registro is not None:
        return registro.data_referencia
    return as_of_das_posicoes(session)


def data_de_corte(session: Session) -> date | None:
    candidatas = [d for d in (extrato_mais_recente(session), referencia_da_carteira(session)) if d]
    return max(candidatas) if candidatas else None


def registrar_referencia(
    session: Session, data_ref: date, origem: str = "import", now: datetime | None = None
) -> ReferenciaCarteira:
    """Grava a data que a carteira passou a refletir (sem commit)."""
    registro = session.exec(select(ReferenciaCarteira)).first()
    if registro is None:
        registro = ReferenciaCarteira(data_referencia=data_ref, origem=origem)
    registro.data_referencia = data_ref
    registro.origem = origem
    registro.atualizado_em = now or datetime.now(timezone.utc)
    session.add(registro)
    return registro


def arquivar_extrato(
    session: Session,
    preview: dict,
    bruto: dict | None,
    arquivo: str | None,
    data_ref: date,
    now: datetime,
) -> tuple[ExtratoImportado, bool]:
    """
    Grava (ou corrige) o extrato daquele mês. Retorna (registro, era_novo).

    O payload é o `bruto` do parser quando existe — ele tem as movimentações, que o
    preview omite. Sem bruto (gravação manual, testes), guarda o preview: melhor
    arquivar o que se tem do que perder o mês.
    """
    proventos = preview.get("proventos_do_mes") or {}
    payload = bruto if bruto is not None else preview

    registro = session.exec(
        select(ExtratoImportado).where(ExtratoImportado.data_referencia == data_ref)
    ).first()
    era_novo = registro is None

    if registro is None:
        registro = ExtratoImportado(data_referencia=data_ref, payload_json="{}", importado_em=now)

    # O upload já mascara; aqui de novo porque gravações manuais e testes chegam por fora.
    registro.arquivo = mascarar_nome_arquivo(arquivo)
    registro.total_posicoes = int(preview.get("total_posicoes") or 0)
    registro.total_valor_mercado = float(preview.get("total_valor_mercado") or 0.0)
    registro.proventos_total = float(proventos.get("total_liquido") or 0.0)
    registro.proventos_quantidade = int(proventos.get("quantidade") or 0)
    registro.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    registro.atualizado_em = now

    session.add(registro)
    logger.info(
        "arquivar_extrato: %s ref=%s (%d posicoes, R$ %.2f, %d provento(s))",
        "criado" if era_novo else "atualizado", data_ref,
        registro.total_posicoes, registro.total_valor_mercado, registro.proventos_quantidade,
    )
    return registro, era_novo


def excluir_mes(session: Session, data_ref: date) -> bool:
    """
    Apaga um mês arquivado (sem commit). Leva junto o que só existe por causa dele: as
    regras de linha e de ativo daquele mês e o SnapshotMensal legado da mesma data.
    Não toca em Posicao — excluir o histórico não desfaz o que o import fez na carteira.
    """
    registro = session.exec(
        select(ExtratoImportado).where(ExtratoImportado.data_referencia == data_ref)
    ).first()
    if registro is None:
        return False
    session.delete(registro)
    for snap in session.exec(
        select(SnapshotMensal).where(SnapshotMensal.data_referencia == data_ref)
    ).all():
        try:
            origem = json.loads(snap.payload_json).get("origem")
        except (json.JSONDecodeError, AttributeError):
            origem = None
        if origem == "extrato_btg_xlsx":
            session.delete(snap)
    regras = excluir_do_mes(session, data_ref)
    logger.info("excluir_mes: %s apagado (%d regra(s) do mes)", data_ref, regras)
    return True
