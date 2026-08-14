"""
Tool atualizar_estrategia — persiste mudanças na tese e planos futuros (PLANO §13 Fase 5).

Espelha gravar_posicoes: tool de escrita separada, chamada SOMENTE no turno de confirmação
após o usuário dizer "sim" explicitamente (guardrail — PLANO §10 / spec_persistencia_estrategia.md).
Nunca lança exceção para dentro do loop (contrato de tools — PLANO §3).
"""
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..database import engine
from ..models.estrategia import EstrategiaInvestimento, HistoricoEstrategia, PlanoFuturo, StatusPlano
from .schemas import tool_error

logger = logging.getLogger(__name__)


async def tool_atualizar_estrategia(mudancas: dict) -> dict:
    """Atualiza tese e/ou planos futuros. Nunca lança exceção."""
    try:
        return await _atualizar(mudancas)
    except Exception as e:
        logger.error("atualizar_estrategia: erro inesperado: %s", e)
        return tool_error(f"Erro interno ao atualizar estratégia: {e}")


async def _atualizar(mudancas: dict) -> dict:
    now = datetime.now(timezone.utc)
    resumo: list[str] = []

    with Session(engine) as session:
        estrategia = session.exec(select(EstrategiaInvestimento)).first()
        if not estrategia:
            estrategia = EstrategiaInvestimento(tese="", version=1, updated_at=now)
            session.add(estrategia)
            session.flush()

        # --- Atualizar tese ---
        nova_tese = mudancas.get("tese")
        if nova_tese is not None:
            tese_anterior = estrategia.tese
            estrategia.tese = nova_tese.strip()
            estrategia.version += 1
            estrategia.updated_at = now
            session.add(HistoricoEstrategia(
                estrategia_id=estrategia.id,
                timestamp=now,
                origem="usuário via chat",
                campo="tese",
                valor_anterior=tese_anterior[:500] if tese_anterior else None,
                valor_novo=nova_tese[:500],
            ))
            resumo.append(f"Tese atualizada (versão {estrategia.version})")

        # --- Adicionar planos ---
        for p in (mudancas.get("planos_adicionar") or []):
            session.add(PlanoFuturo(
                estrategia_id=estrategia.id,
                descricao=p.get("descricao", ""),
                gatilho=p.get("gatilho"),
                horizonte=p.get("horizonte"),
                status=StatusPlano.ATIVO,
                created_at=now,
                updated_at=now,
            ))
            resumo.append(f"Plano adicionado: '{p.get('descricao', '')}'")

        # --- Atualizar planos existentes ---
        for upd in (mudancas.get("planos_atualizar") or []):
            pid = upd.get("id")
            if not pid:
                continue
            plano = session.get(PlanoFuturo, pid)
            if not plano:
                resumo.append(f"Plano id={pid} não encontrado — ignorado")
                continue
            for campo in ("descricao", "gatilho", "horizonte"):
                if campo in upd:
                    setattr(plano, campo, upd[campo])
            if "status" in upd:
                try:
                    plano.status = StatusPlano(upd["status"])
                except ValueError:
                    pass
            plano.updated_at = now
            resumo.append(f"Plano id={pid} atualizado")

        # --- Cancelar planos ---
        for pid in (mudancas.get("planos_remover") or []):
            plano = session.get(PlanoFuturo, pid)
            if plano:
                plano.status = StatusPlano.CANCELADO
                plano.updated_at = now
                resumo.append(f"Plano id={pid} cancelado")

        session.commit()
        session.refresh(estrategia)
        version_nova = estrategia.version

    if not resumo:
        return tool_error("Nenhuma mudança especificada em 'mudancas' (tese, planos_adicionar, planos_atualizar, planos_remover).")

    logger.info("atualizar_estrategia: %s", "; ".join(resumo))
    return {
        "ok": True,
        "version_nova": version_nova,
        "resumo": "; ".join(resumo),
        "timestamp": now.isoformat(),
    }
