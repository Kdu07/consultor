"""
Tool calcular_desvio — snapshot coerente da carteira vs. alvos (PLANO §8).

Snapshot coerente (§8.1):
  - ACAO, FII, ETF, BDR, TESOURO com ticker → preço ao vivo via PriceProvider (com cache)
  - RF, FUNDO, CAIXA sem cotação pública → valor do extrato (source="extrato")

Retorna por classe e por ativo:
  - desvio em p.p. e R$
  - flag dentro/fora da banda (regra 5/25 — decisão da tool, não do modelo)
  - fração ao-vivo vs. extrato
  - as_of mais antigo
  - data da última atualização de posições
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from ..config import get_settings
from ..database import engine
from ..models.alvo import AlvoAtivo, AlvoClasse
from ..models.config_rebalanceamento import ConfigRebalanceamento
from ..models.posicao import ClasseAtivo, Posicao
from .ativo import tool_dados_ativo
from .schemas import tool_error

logger = logging.getLogger(__name__)

# Classes que têm preço ao vivo via provider
_CLASSES_AO_VIVO = {ClasseAtivo.ACAO, ClasseAtivo.FII, ClasseAtivo.ETF, ClasseAtivo.BDR, ClasseAtivo.TESOURO}


def _fora_da_banda(atual_pct: float, alvo_pct: float, cfg: ConfigRebalanceamento) -> bool:
    if alvo_pct == 0:
        return atual_pct > 0
    desvio_abs = abs(atual_pct - alvo_pct)
    desvio_rel = desvio_abs / alvo_pct * 100.0
    return desvio_abs >= cfg.banda_absoluta_pp or desvio_rel >= cfg.banda_relativa_pct


def _acima_piso(desvio_reais: float, valor_total: float, cfg: ConfigRebalanceamento) -> bool:
    """Retorna True se o desvio em R$ está acima do piso de irrelevância."""
    return (
        abs(desvio_reais) >= cfg.piso_reais
        or (valor_total > 0 and abs(desvio_reais) / valor_total * 100 >= cfg.piso_percentual)
    )


async def tool_calcular_desvio() -> dict:
    """
    Calcula desvio da carteira vs. alvos em snapshot coerente.
    Nunca lança exceção.
    """
    try:
        return await _calcular()
    except Exception as e:
        logger.error("calcular_desvio: erro inesperado: %s", e)
        return tool_error(f"Erro interno ao calcular desvio: {e}")


async def _calcular() -> dict:
    # ------------------------------------------------------------------
    # 1. Ler dados do banco
    # ------------------------------------------------------------------
    with Session(engine) as session:
        posicoes = session.exec(select(Posicao).where(Posicao.ativo == True)).all()
        alvos_classe_rows = session.exec(select(AlvoClasse)).all()
        alvos_ativo_rows = session.exec(select(AlvoAtivo)).all()
        cfg = session.exec(select(ConfigRebalanceamento)).first()

    if not posicoes:
        return tool_error("Carteira vazia. Adicione posições antes de calcular o desvio.")

    alvos_classe: dict[str, float] = {a.classe.value: a.percentual for a in alvos_classe_rows}
    alvos_ativo: dict[str, float] = {a.identificador.upper(): a.percentual for a in alvos_ativo_rows}

    # ------------------------------------------------------------------
    # 2. Buscar preços ao vivo em paralelo (só para classes com cotação)
    # ------------------------------------------------------------------
    pos_ao_vivo = [p for p in posicoes if p.classe in _CLASSES_AO_VIVO and p.ticker]
    pos_extrato  = [p for p in posicoes if p not in pos_ao_vivo]

    preco_results: list[dict] = []
    if pos_ao_vivo:
        preco_results = list(await asyncio.gather(*[
            tool_dados_ativo(p.ticker) for p in pos_ao_vivo
        ]))

    price_map: dict[int, dict] = {}
    for p, res in zip(pos_ao_vivo, preco_results):
        price_map[p.id] = res

    # ------------------------------------------------------------------
    # 3. Calcular valor de cada posição
    # ------------------------------------------------------------------
    now = datetime.now(timezone.utc)
    valor_ao_vivo = 0.0
    valor_extrato  = 0.0
    oldest_as_of: Optional[datetime] = None
    pos_data: list[dict] = []

    for p in posicoes:
        res = price_map.get(p.id)
        if res and "error" not in res:
            # Preço ao vivo disponível
            preco = res["price"]
            valor = p.quantidade * preco
            source = res.get("source", p.source)
            as_of_str = res.get("as_of", now.isoformat())
            try:
                as_of_dt = datetime.fromisoformat(as_of_str)
                if as_of_dt.tzinfo is None:
                    as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
            except Exception:
                as_of_dt = now
            is_live = True
            valor_ao_vivo += valor
        else:
            # Fallback para valor do extrato
            if res and "error" in res:
                logger.warning("calcular_desvio: %s sem cotacao ao vivo — usando extrato", p.ticker)
            valor = p.valor_mercado or 0.0
            source = p.source or "extrato"
            as_of_dt = p.as_of or now
            if as_of_dt.tzinfo is None:
                as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
            is_live = False
            valor_extrato += valor

        if oldest_as_of is None or as_of_dt < oldest_as_of:
            oldest_as_of = as_of_dt

        pos_data.append({
            "id": p.id,
            "ticker": p.ticker,
            "nome": p.nome,
            "classe": p.classe.value,
            "quantidade": p.quantidade,
            "valor": round(valor, 2),
            "source": source,
            "as_of": as_of_dt.isoformat(),
            "is_live": is_live,
        })

    valor_total = valor_ao_vivo + valor_extrato
    if valor_total == 0:
        return tool_error("Valor total da carteira é zero — verifique as posições.")

    # ------------------------------------------------------------------
    # 4. Desvio por classe
    # ------------------------------------------------------------------
    valores_classe: dict[str, float] = {}
    for pd in pos_data:
        c = pd["classe"]
        valores_classe[c] = valores_classe.get(c, 0.0) + pd["valor"]

    todas_classes = set(list(alvos_classe.keys()) + list(valores_classe.keys()))
    desvio_por_classe = []
    for classe in sorted(todas_classes):
        val = valores_classe.get(classe, 0.0)
        atual_pct = val / valor_total * 100 if valor_total > 0 else 0.0
        alvo_pct = alvos_classe.get(classe, 0.0)
        desvio_pp = round(atual_pct - alvo_pct, 2)
        desvio_reais = round(val - (alvo_pct / 100 * valor_total), 2)

        flag_banda = None
        flag_relevante = None
        if cfg and alvo_pct > 0:
            flag_banda = _fora_da_banda(atual_pct, alvo_pct, cfg)
            flag_relevante = _acima_piso(desvio_reais, valor_total, cfg)

        desvio_por_classe.append({
            "classe": classe,
            "valor": round(val, 2),
            "percentual_atual": round(atual_pct, 2),
            "percentual_alvo": alvo_pct,
            "desvio_pp": desvio_pp,
            "desvio_reais": desvio_reais,
            "fora_da_banda": flag_banda,
            "acima_do_piso": flag_relevante,
        })

    # ------------------------------------------------------------------
    # 5. Desvio por ativo
    # ------------------------------------------------------------------
    desvio_por_ativo = []
    for pd in pos_data:
        ticker = (pd["ticker"] or "").upper()
        alvo_pct = alvos_ativo.get(ticker) if ticker else None
        atual_pct = pd["valor"] / valor_total * 100 if valor_total > 0 else 0.0
        desvio_pp = round(atual_pct - alvo_pct, 2) if alvo_pct is not None else None
        desvio_reais = round(pd["valor"] - (alvo_pct / 100 * valor_total), 2) if alvo_pct is not None else None

        flag_banda = None
        flag_relevante = None
        if cfg and alvo_pct is not None:
            flag_banda = _fora_da_banda(atual_pct, alvo_pct, cfg)
            flag_relevante = _acima_piso(desvio_reais, valor_total, cfg)

        desvio_por_ativo.append({
            "ticker": pd["ticker"],
            "nome": pd["nome"],
            "classe": pd["classe"],
            "valor": pd["valor"],
            "percentual_atual": round(atual_pct, 2),
            "percentual_alvo": alvo_pct,
            "desvio_pp": desvio_pp,
            "desvio_reais": desvio_reais,
            "fora_da_banda": flag_banda,
            "acima_do_piso": flag_relevante,
            "source": pd["source"],
            "as_of": pd["as_of"],
            "is_live": pd["is_live"],
        })

    # ------------------------------------------------------------------
    # 6. Metadados do snapshot
    # ------------------------------------------------------------------
    data_ultima_atualizacao = max(
        (p.atualizado_em for p in posicoes if p.atualizado_em),
        default=None,
    )
    fracao_ao_vivo = round(valor_ao_vivo / valor_total * 100, 1) if valor_total > 0 else 0.0
    fracao_extrato = round(100 - fracao_ao_vivo, 1)

    algum_fora = any(
        d.get("fora_da_banda") and d.get("acima_do_piso")
        for d in desvio_por_classe
    )

    logger.info(
        "calcular_desvio: total=R$%.2f | ao_vivo=%.1f%% | extrato=%.1f%% | fora_da_banda=%s",
        valor_total, fracao_ao_vivo, fracao_extrato, algum_fora,
    )

    return {
        "snapshot": {
            "data_hora": now.isoformat(),
            "valor_total": round(valor_total, 2),
            "fracao_ao_vivo_pct": fracao_ao_vivo,
            "fracao_extrato_pct": fracao_extrato,
            "as_of_mais_antigo": oldest_as_of.isoformat() if oldest_as_of else None,
            "data_ultima_atualizacao_posicoes": (
                data_ultima_atualizacao.isoformat() if data_ultima_atualizacao else None
            ),
        },
        "algum_fora_da_banda": algum_fora,
        "por_classe": desvio_por_classe,
        "por_ativo": desvio_por_ativo,
        "config_banda": {
            "banda_absoluta_pp": cfg.banda_absoluta_pp if cfg else 5.0,
            "banda_relativa_pct": cfg.banda_relativa_pct if cfg else 25.0,
            "piso_reais": cfg.piso_reais if cfg else 500.0,
        } if cfg else None,
        "nota_alvos_ativo": (
            "Alvos por ativo não definidos — desvio por ativo não calculado."
            if not alvos_ativo else None
        ),
    }
