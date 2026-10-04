"""
Arquivamento do extrato importado — o histórico que a tabela Posicao não guarda.

Por que existe (ver docstring de ExtratoImportado): `gravar_posicoes` faz upsert
destrutivo. Quantidade e valor do mês anterior são sobrescritos, e proventos,
movimentações, aluguel e valores em trânsito viviam só no preview em memória, que é
descartado logo depois. Sem isto, importar setembro apaga a foto de agosto.

São duas escritas, ambas idempotentes por `data_referencia`:

  1. ExtratoImportado — o extrato inteiro do parser, como veio.
  2. SnapshotMensal   — a carteira valorada naquela data, para o gráfico do dashboard.

Idempotência importa porque reimportar o mesmo mês é rotina (o usuário corrige um
arquivo, reenvia o mesmo XLSX): o mês é corrigido no lugar, nunca duplicado.

As funções recebem a Session de quem chama e NÃO fazem commit: o arquivamento entra na
mesma transação da gravação das posições. Ou o mês inteiro é gravado — posições,
histórico e snapshot — ou nada é.
"""
import json
import logging
from datetime import date, datetime

from sqlmodel import Session, select

from ..models.extrato import ExtratoImportado
from ..models.snapshot_mensal import SnapshotMensal

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

    registro.arquivo = arquivo
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


def snapshot_do_extrato(
    session: Session,
    preview: dict,
    data_ref: date,
    now: datetime,
) -> tuple[SnapshotMensal, bool]:
    """
    Fotografia da carteira na data do extrato. Retorna (snapshot, era_novo).

    Diferente de POST /snapshots, que valora com o cache de cotações do dia: aqui o
    valor é o do próprio extrato, que é o número oficial do BTG naquela data. Buscar
    preço ao vivo para uma data passada daria um total que nunca existiu.

    Reimportar o mesmo mês reescreve o snapshot daquela data em vez de empilhar outro —
    senão o gráfico do dashboard ganharia dois pontos para o mesmo mês.
    """
    posicoes = preview.get("posicoes") or []
    itens = [
        {
            "ticker": p.get("ticker"),
            "nome": p.get("nome"),
            "classe": p.get("classe"),
            "quantidade": p.get("quantidade"),
            "valor": round(float(p.get("valor_mercado") or 0.0), 2),
            "source": "extrato",
            "as_of": p.get("as_of"),
        }
        for p in posicoes
    ]
    total = round(float(preview.get("total_valor_mercado") or 0.0), 2)

    payload = {
        "data": data_ref.isoformat(),
        "valor_total": total,
        "posicoes": itens,
        "origem": "extrato_btg_xlsx",
    }

    snap = session.exec(
        select(SnapshotMensal).where(SnapshotMensal.data_referencia == data_ref)
    ).first()
    era_novo = snap is None

    if snap is None:
        snap = SnapshotMensal(data_referencia=data_ref, valor_total=total, payload_json="{}",
                              criado_em=now)
    snap.valor_total = total
    snap.payload_json = json.dumps(payload, ensure_ascii=False, default=str)

    session.add(snap)
    logger.info(
        "snapshot_do_extrato: %s ref=%s total=R$ %.2f (%d posicoes)",
        "criado" if era_novo else "atualizado", data_ref, total, len(itens),
    )
    return snap, era_novo
