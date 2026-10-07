"""
Endpoint de dashboard — retorna dados da carteira para a UI sem invocar o loop do agente.
Usa cache de cotações (QuoteCache) para preços recentes.
GET /dashboard
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlmodel import Session, select

from ..config import get_settings
from ..database import engine
from ..models.alvo import AlvoAtivo, AlvoClasse
from ..models.config_rebalanceamento import ConfigRebalanceamento
from ..models.posicao import ClasseAtivo, Posicao
from ..models.quote_cache import QuoteCache
from ..models.extrato import ExtratoImportado
from ..tools.valuation import valor_offline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

# Classes com cotação ao vivo via cache
_CLASSES_AO_VIVO = {ClasseAtivo.ACAO, ClasseAtivo.FII, ClasseAtivo.ETF, ClasseAtivo.BDR, ClasseAtivo.TESOURO}


@router.get("/dashboard")
def get_dashboard():
    """
    Dados da carteira para o dashboard:
      - posições com valor calculado (cache de cotações ou extrato)
      - alocação atual vs. alvo por classe
      - metadados de frescor
    Não invoca o loop do agente — leitura direta do banco.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    ttl_cutoff = now - timedelta(seconds=settings.quote_cache_ttl_seconds)

    with Session(engine) as session:
        posicoes = session.exec(select(Posicao).where(Posicao.ativo == True)).all()
        alvos_classe_rows = session.exec(select(AlvoClasse)).all()
        alvos_ativo_rows = session.exec(select(AlvoAtivo)).all()
        cfg = session.exec(select(ConfigRebalanceamento)).first()

        # Cache de cotações recente
        cache_map: dict[str, dict] = {}
        for p in posicoes:
            if p.ticker and p.classe in _CLASSES_AO_VIVO:
                row = session.exec(
                    select(QuoteCache)
                    .where(QuoteCache.ticker == p.ticker.upper())
                    .where(QuoteCache.fetched_at >= ttl_cutoff)
                    .order_by(QuoteCache.fetched_at.desc())
                ).first()
                if row:
                    cache_map[p.ticker.upper()] = {
                        "price": row.price,
                        "source": row.source,
                        "as_of": row.fetched_at.isoformat(),
                    }

        # Último fechamento arquivado: a base do "Δ desde o fechamento" do painel. O
        # total_valor_mercado é a soma das posições do extrato — a mesma base do total
        # ao vivo acima (sem valores em trânsito).
        ultimo_fechamento = session.exec(
            select(ExtratoImportado).order_by(ExtratoImportado.data_referencia.desc())
        ).first()

    alvos_classe = {a.classe.value: a.percentual for a in alvos_classe_rows}
    alvos_ativo = {a.identificador.upper(): a.percentual for a in alvos_ativo_rows}

    # ------------------------------------------------------------------
    # Grandezas do Sumário do último extrato (vocabulário oficial):
    #   valor_posicoes    — Σ posições, sem valores em trânsito (= total_valor_mercado)
    #   patrimonio_bruto  — Total Bruto do Sumário, com trânsito (o nº do histórico)
    #   saldo_liquido_btg — Total LÍQUIDO do Sumário: o número que o app do BTG
    #                       tende a mostrar — serve para conferência direta.
    # Payload v1/v2 não tem sumário/validação → campos ficam None.
    # ------------------------------------------------------------------
    patrimonio_bruto: float | None = None
    saldo_liquido_btg: float | None = None
    validacao_veredito: str | None = None
    if ultimo_fechamento:
        try:
            payload_fechamento = json.loads(ultimo_fechamento.payload_json or "{}")
        except (TypeError, ValueError):
            logger.warning("dashboard: payload ilegível no extrato id=%s", ultimo_fechamento.id)
            payload_fechamento = {}
        total_sumario = (
            ((payload_fechamento.get("sumario") or {}).get("atual") or {}).get("total") or {}
        )
        bruto = total_sumario.get("bruto")
        liquido = total_sumario.get("liquido")
        patrimonio_bruto = round(float(bruto), 2) if bruto is not None else None
        saldo_liquido_btg = round(float(liquido), 2) if liquido is not None else None
        validacao_veredito = (payload_fechamento.get("validacao") or {}).get("veredito")

    # ------------------------------------------------------------------
    # Calcula valor de cada posição
    # ------------------------------------------------------------------
    posicoes_data: list[dict] = []
    total = 0.0
    valor_ao_vivo = 0.0
    valor_extrato = 0.0
    oldest_as_of: datetime | None = None

    for p in posicoes:
        ticker = (p.ticker or "").upper()
        cached = cache_map.get(ticker)

        if cached:
            valor = round(p.quantidade * cached["price"], 2)
            source = cached["source"]
            as_of = cached["as_of"]
            is_live = True
            valor_ao_vivo += valor
            try:
                dt = datetime.fromisoformat(as_of)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if oldest_as_of is None or dt < oldest_as_of:
                    oldest_as_of = dt
            except Exception:
                pass
        else:
            valor_raw, usou_preco_medio = valor_offline(p)
            valor = round(valor_raw, 2)
            source = "preco_medio" if usou_preco_medio else (p.source or "extrato")
            as_of = p.as_of.isoformat() if p.as_of else None
            is_live = False
            valor_extrato += valor
            if p.as_of:
                dt = p.as_of if p.as_of.tzinfo else p.as_of.replace(tzinfo=timezone.utc)
                if oldest_as_of is None or dt < oldest_as_of:
                    oldest_as_of = dt

        total += valor
        posicoes_data.append({
            "id": p.id,
            "ticker": p.ticker,
            "nome": p.nome,
            "classe": p.classe.value,
            "quantidade": p.quantidade,
            "preco_medio": p.preco_medio,
            "valor": valor,
            "source": source,
            "as_of": as_of,
            "is_live": is_live,
        })

    # Ordena por valor decrescente
    posicoes_data.sort(key=lambda x: -x["valor"])

    # Percentuais por posição
    for p in posicoes_data:
        p["percentual"] = round(p["valor"] / total * 100, 2) if total > 0 else 0.0

    # ------------------------------------------------------------------
    # Alocação por classe
    # ------------------------------------------------------------------
    valores_classe: dict[str, float] = {}
    for p in posicoes_data:
        c = p["classe"]
        valores_classe[c] = valores_classe.get(c, 0.0) + p["valor"]

    todas_classes = sorted(set(list(alvos_classe.keys()) + list(valores_classe.keys())))
    por_classe = []
    for classe in todas_classes:
        val = valores_classe.get(classe, 0.0)
        atual_pct = round(val / total * 100, 2) if total > 0 else 0.0
        alvo_pct = alvos_classe.get(classe, 0.0)
        desvio_pp = round(atual_pct - alvo_pct, 2) if alvo_pct else None

        fora_banda = None
        if cfg and alvo_pct:
            desvio_abs = abs(atual_pct - alvo_pct)
            desvio_rel = desvio_abs / alvo_pct * 100
            fora_banda = (
                desvio_abs >= cfg.banda_absoluta_pp
                or desvio_rel >= cfg.banda_relativa_pct
            )

        por_classe.append({
            "classe": classe,
            "valor": round(val, 2),
            "percentual_atual": atual_pct,
            "percentual_alvo": alvo_pct,
            "desvio_pp": desvio_pp,
            "fora_da_banda": fora_banda,
        })

    # ------------------------------------------------------------------
    # Metadados
    # ------------------------------------------------------------------
    data_ultima_pos = max(
        (p.atualizado_em for p in posicoes if p.atualizado_em), default=None
    )

    return {
        "total": round(total, 2),
        "fracao_ao_vivo_pct": round(valor_ao_vivo / total * 100, 1) if total > 0 else 0,
        "fracao_extrato_pct": round(valor_extrato / total * 100, 1) if total > 0 else 0,
        "as_of_mais_antigo": oldest_as_of.isoformat() if oldest_as_of else None,
        "data_ultima_atualizacao_posicoes": (
            data_ultima_pos.isoformat() if data_ultima_pos else None
        ),
        "ultimo_fechamento": {
            "data": ultimo_fechamento.data_referencia.isoformat(),
            "valor_total": ultimo_fechamento.total_valor_mercado,
            # valor_total mantido por compatibilidade; valor_posicoes é o nome oficial.
            "valor_posicoes": ultimo_fechamento.total_valor_mercado,
            "patrimonio_bruto": patrimonio_bruto,
            "saldo_liquido_btg": saldo_liquido_btg,
            "validacao_veredito": validacao_veredito,
        } if ultimo_fechamento else None,
        "posicoes": posicoes_data,
        "por_classe": por_classe,
        "tem_alvos": bool(alvos_classe),
        "tem_alvos_ativo": bool(alvos_ativo),
        "data_hora": now.isoformat(),
    }
