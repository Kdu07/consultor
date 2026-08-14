"""
Tool gravar_posicoes — salva as posições do preview no banco de dados.

Guardrail 4 (PLANO §3): esta tool SÓ deve ser chamada no turno de confirmação,
após o usuário dizer "sim" explicitamente. A arquitetura garante isso: a gravação
existe apenas aqui, não em importar_extrato.

Fonte da verdade: o preview em extrato_staging, não a lista que o modelo reescreve.
O modelo repetir 15 posições no argumento da tool é um caminho de perda de dados
(truncar a lista, arredondar valores) — e, com reconciliação, uma lista truncada
desativaria posições boas. O argumento `posicoes` continua aceito para gravação
manual (sem extrato em staging) e serve de conferência quando há staging.

Lógica de upsert: casa por `chave_externa` (identidade do papel), com fallback
ticker → nome para as linhas anteriores à migração — ver _achar_posicao.

Reconciliação (lote de extrato): o extrato é a carteira completa na data de
referência, então toda posição ativa fora do lote é marcada ativo=False. Sem isso
a carteira nunca "encolhe": ativos vendidos, resgatados ou vindos do seed inicial
ficam somando no dashboard para sempre. Isso vale inclusive para posições criadas à
mão em POST /posicoes — decisão consciente: o extrato do BTG manda na carteira toda.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from ..database import engine
from ..models.posicao import ClasseAtivo, Posicao
from . import extrato_staging
from .schemas import tool_error

logger = logging.getLogger(__name__)


def _parse_classe(classe_str: str) -> ClasseAtivo:
    try:
        return ClasseAtivo(classe_str.upper())
    except ValueError:
        return ClasseAtivo.RF


def _parse_date(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        if isinstance(s, str):
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return s
    except Exception:
        return None


def _achar_posicao(session: Session, chave: str | None, ticker: str | None, nome: str) -> Posicao | None:
    """
    Identidade em cascata, da mais estável para a mais frágil:
      1. chave_externa — identidade do papel, imune à reescrita de nome pelo BTG
      2. ticker        — posições anteriores à chave e as criadas à mão
      3. nome          — último recurso (RF/FUNDO/CAIXA antigos, sem ticker)
    Casando por 2 ou 3, quem chama grava a chave na linha: o banco se migra sozinho
    no primeiro import, sem backfill adivinhando papel a partir do nome.
    """
    def _uma(condicao):
        return session.exec(
            select(Posicao).where(condicao).where(Posicao.ativo == True)
        ).first()

    if chave:
        achada = _uma(Posicao.chave_externa == chave)
        if achada:
            return achada
        # Papel que voltou à carteira (vendido e recomprado, RF que rolou): reativa a
        # linha original em vez de abrir outra. Só a chave autoriza isso — ressuscitar
        # por nome traria de volta lixo que a reconciliação tinha acabado de baixar.
        inativa = session.exec(
            select(Posicao)
            .where(Posicao.chave_externa == chave)
            .where(Posicao.ativo == False)
            .order_by(Posicao.atualizado_em.desc())
        ).first()
        if inativa:
            return inativa
        # Uma linha com OUTRA chave é outro papel — nome ou ticker iguais são coincidência
        # (dois CDBs do mesmo banco com vencimentos diferentes têm o mesmo nome curto).
    if ticker:
        achada = _uma(Posicao.ticker == ticker)
        if achada and not (chave and achada.chave_externa and achada.chave_externa != chave):
            return achada
    achada = _uma(Posicao.nome == nome)
    if achada and not (chave and achada.chave_externa and achada.chave_externa != chave):
        return achada
    return None


def _resolver_lote(posicoes: list[dict] | None) -> tuple[list[dict], bool, str | None]:
    """
    Decide o que gravar: (lote, veio_do_extrato, aviso).

    Com extrato em staging, o preview é a fonte da verdade e o lote é completo —
    a reconciliação pode rodar. Sem staging, grava-se o que o modelo passou e
    nenhuma posição é desativada.
    """
    estado = extrato_staging.get()
    if not estado:
        return (posicoes or []), False, None

    preview = estado["preview"].get("posicoes") or []
    aviso = None
    if posicoes is not None and len(posicoes) != len(preview):
        aviso = (
            f"A lista enviada tinha {len(posicoes)} posição(ões) e o extrato em staging "
            f"tem {len(preview)}. Gravei as {len(preview)} do extrato."
        )
        logger.warning("gravar_posicoes: %s", aviso)
    return preview, True, aviso


async def tool_gravar_posicoes(posicoes: list[dict] | None = None) -> dict:
    """
    Grava as posições confirmadas pelo usuário no banco.
    Nunca deve ser chamada sem confirmação explícita ("sim").
    """
    lote, veio_do_extrato, aviso_lote = _resolver_lote(posicoes)
    if not lote:
        return tool_error(
            "Nada a gravar: nenhum extrato em staging e nenhuma posição informada. "
            "Peça ao usuário para enviar o XLSX pelo botão 'Importar extrato BTG'."
        )

    now = datetime.now(timezone.utc)
    criados = 0
    atualizados = 0
    erros: list[str] = []
    reativadas: list[str] = []
    ids_no_lote: set[int] = set()

    with Session(engine) as session:
        for item in lote:
            try:
                ticker = (item.get("ticker") or "").strip() or None
                nome = (item.get("nome") or "").strip()
                classe = _parse_classe(item.get("classe", "RF"))
                quantidade = float(item.get("quantidade", 0))
                preco_medio = item.get("preco_medio")
                valor_mercado = item.get("valor_mercado")
                as_of = _parse_date(item.get("as_of"))
                # Renda fixa: vencimento e taxa vêm do extrato XLSX (podem ser None em RV)
                vencimento = _parse_date(item.get("vencimento"))
                taxa_contratada = (item.get("taxa_contratada") or "").strip() or None
                chave_externa = (item.get("chave_externa") or "").strip() or None

                if not nome:
                    erros.append(f"Posição sem nome ignorada: {item}")
                    continue

                existing = _achar_posicao(session, chave_externa, ticker, nome)

                if existing:
                    if not existing.ativo:
                        existing.ativo = True
                        reativadas.append(existing.ticker or nome)
                    existing.chave_externa = chave_externa or existing.chave_externa
                    existing.nome = nome
                    existing.ticker = ticker
                    existing.classe = classe
                    existing.quantidade = quantidade
                    existing.preco_medio = float(preco_medio) if preco_medio is not None else None
                    existing.valor_mercado = float(valor_mercado) if valor_mercado is not None else None
                    existing.vencimento = vencimento
                    existing.taxa_contratada = taxa_contratada
                    existing.source = "extrato"
                    existing.as_of = as_of
                    existing.atualizado_em = now
                    session.add(existing)
                    atualizados += 1
                    if existing.id is not None:
                        ids_no_lote.add(existing.id)
                else:
                    nova = Posicao(
                        chave_externa=chave_externa,
                        ticker=ticker,
                        nome=nome,
                        classe=classe,
                        quantidade=quantidade,
                        preco_medio=float(preco_medio) if preco_medio is not None else None,
                        valor_mercado=float(valor_mercado) if valor_mercado is not None else None,
                        vencimento=vencimento,
                        taxa_contratada=taxa_contratada,
                        source="extrato",
                        as_of=as_of,
                        atualizado_em=now,
                    )
                    session.add(nova)
                    # flush para obter o id e não desativar a posição recém-criada
                    session.flush()
                    criados += 1
                    if nova.id is not None:
                        ids_no_lote.add(nova.id)

            except Exception as e:
                erros.append(f"Erro ao processar '{item.get('ticker', item.get('nome', '?'))}': {e}")

        # Reconciliação: o extrato é a carteira completa naquela data de referência.
        # Só roda em lote de extrato e só se nada falhou — um lote parcial desativaria
        # posições que na verdade existem.
        desativadas: list[dict] = []
        if veio_do_extrato and not erros:
            ausentes = session.exec(
                select(Posicao).where(Posicao.ativo == True)
            ).all()
            for p in ausentes:
                if p.id in ids_no_lote:
                    continue
                p.ativo = False
                p.atualizado_em = now
                session.add(p)
                desativadas.append({
                    "ticker": p.ticker,
                    "nome": p.nome,
                    "classe": p.classe.value,
                    "ultimo_valor": p.valor_mercado,
                })

        session.commit()

    # O preview é de uso único: consumido, sai do staging. Assim uma gravação manual
    # posterior ("adicione tal posição") não é confundida com o lote do extrato.
    if veio_do_extrato and not erros:
        extrato_staging.clear()

    logger.info(
        "gravar_posicoes: %d criadas, %d atualizadas, %d reativadas, %d desativadas, %d erros",
        criados, atualizados, len(reativadas), len(desativadas), len(erros),
    )

    result: dict = {
        "posicoes_criadas": criados,
        "posicoes_atualizadas": atualizados,
        "total_gravadas": criados + atualizados,
        "posicoes_desativadas": desativadas,
        "posicoes_reativadas": reativadas,
        "data_gravacao": now.isoformat(),
        "source": "extrato",
    }

    avisos = list(erros)
    if aviso_lote:
        avisos.append(aviso_lote)
    if desativadas:
        nomes = ", ".join(d["ticker"] or d["nome"] for d in desativadas)
        avisos.append(
            f"{len(desativadas)} posição(ões) não apareceram neste extrato e saíram da "
            f"carteira: {nomes}. DIGA isso ao usuário — pode ser venda/resgate, mas também "
            f"pode ser ativo em outra corretora que o extrato do BTG não cobre."
        )
    if reativadas:
        avisos.append(
            f"Voltaram à carteira depois de terem saído em algum extrato anterior: "
            f"{', '.join(reativadas)}."
        )
    if erros and veio_do_extrato:
        avisos.append(
            "Não desativei nenhuma posição porque houve erro no lote — a carteira pode "
            "ter ativos que já não existem no extrato."
        )
    if avisos:
        result["avisos"] = avisos
    return result
