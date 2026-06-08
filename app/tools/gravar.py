"""
Tool gravar_posicoes — salva posições do preview no banco de dados.

Guardrail 4 (PLANO §3): esta tool SÓ deve ser chamada no turno de confirmação,
após o usuário dizer "sim" explicitamente. A arquitetura garante isso: a gravação
existe apenas aqui, não em importar_extrato.

Lógica de upsert:
  - Com ticker (ACAO, FII, ETF, BDR, TESOURO): upsert por ticker
  - Sem ticker (RF, FUNDO, CAIXA): upsert por nome
"""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from ..database import engine
from ..models.posicao import ClasseAtivo, Posicao
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


async def tool_gravar_posicoes(posicoes: list[dict]) -> dict:
    """
    Grava as posições confirmadas pelo usuário no banco.
    Nunca deve ser chamada sem confirmação explícita ("sim").
    """
    if not posicoes:
        return tool_error("Lista de posições vazia — nada a gravar.")

    now = datetime.now(timezone.utc)
    criados = 0
    atualizados = 0
    erros: list[str] = []

    with Session(engine) as session:
        for item in posicoes:
            try:
                ticker = (item.get("ticker") or "").strip() or None
                nome = (item.get("nome") or "").strip()
                classe = _parse_classe(item.get("classe", "RF"))
                quantidade = float(item.get("quantidade", 0))
                preco_medio = item.get("preco_medio")
                valor_mercado = item.get("valor_mercado")
                as_of = _parse_date(item.get("as_of"))

                if not nome:
                    erros.append(f"Posição sem nome ignorada: {item}")
                    continue

                # Busca posição existente
                existing = None
                if ticker:
                    existing = session.exec(
                        select(Posicao)
                        .where(Posicao.ticker == ticker)
                        .where(Posicao.ativo == True)
                    ).first()
                if not existing:
                    existing = session.exec(
                        select(Posicao)
                        .where(Posicao.nome == nome)
                        .where(Posicao.ativo == True)
                    ).first()

                if existing:
                    existing.nome = nome
                    existing.ticker = ticker
                    existing.classe = classe
                    existing.quantidade = quantidade
                    existing.preco_medio = float(preco_medio) if preco_medio is not None else None
                    existing.valor_mercado = float(valor_mercado) if valor_mercado is not None else None
                    existing.source = "extrato"
                    existing.as_of = as_of
                    existing.atualizado_em = now
                    session.add(existing)
                    atualizados += 1
                else:
                    nova = Posicao(
                        ticker=ticker,
                        nome=nome,
                        classe=classe,
                        quantidade=quantidade,
                        preco_medio=float(preco_medio) if preco_medio is not None else None,
                        valor_mercado=float(valor_mercado) if valor_mercado is not None else None,
                        source="extrato",
                        as_of=as_of,
                        atualizado_em=now,
                    )
                    session.add(nova)
                    criados += 1

            except Exception as e:
                erros.append(f"Erro ao processar '{item.get('ticker', item.get('nome', '?'))}': {e}")

        session.commit()

    logger.info(
        "gravar_posicoes: %d criadas, %d atualizadas, %d erros",
        criados, atualizados, len(erros),
    )

    result: dict = {
        "posicoes_criadas": criados,
        "posicoes_atualizadas": atualizados,
        "total_gravadas": criados + atualizados,
        "data_gravacao": now.isoformat(),
        "source": "extrato",
    }
    if erros:
        result["avisos"] = erros
    return result
