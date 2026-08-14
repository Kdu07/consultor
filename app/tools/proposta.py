"""
Tool proposta_rebalanceamento — simulação what-if de pré-trade (PLANO §13 Fase 5).

Aplica operações hipotéticas (comprar/vender) sobre o snapshot atual da carteira,
recalcula alocação vs. alvos e reporta fração de liquidez.
Não altera o banco — análise pura.
"""
import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..database import engine
from ..models.alvo import AlvoAtivo, AlvoClasse
from ..models.config_rebalanceamento import ConfigRebalanceamento
from ..models.posicao import ClasseAtivo
from .desvio import _fora_da_banda
from .schemas import tool_error

logger = logging.getLogger(__name__)

# Classes líquidas (D+3 ou melhor) para cálculo da trava de liquidez
_CLASSES_LIQUIDAS = {
    ClasseAtivo.ACAO, ClasseAtivo.ETF, ClasseAtivo.FII,
    ClasseAtivo.BDR, ClasseAtivo.CAIXA, ClasseAtivo.TESOURO,
}


async def tool_proposta_rebalanceamento(operacoes: list[dict]) -> dict:
    """Simula operações hipotéticas. Nunca altera o banco. Nunca lança exceção."""
    try:
        return await _proposta(operacoes)
    except Exception as e:
        logger.error("proposta_rebalanceamento: erro inesperado: %s", e)
        return tool_error(f"Erro interno na proposta: {e}")


async def _proposta(operacoes: list[dict]) -> dict:
    # Importação local para evitar circular (desvio → ativo → providers)
    from .desvio import tool_calcular_desvio

    if not operacoes:
        return tool_error("Nenhuma operação fornecida em 'operacoes'.")

    # ------------------------------------------------------------------
    # 1. Snapshot atual via calcular_desvio (busca preços ao vivo)
    # ------------------------------------------------------------------
    desvio_atual = await tool_calcular_desvio()
    if "error" in desvio_atual:
        return desvio_atual

    snap = desvio_atual["snapshot"]
    valor_total_atual = snap["valor_total"]

    # Índice de ativos pelo identificador (ticker ou nome) em maiúsculo
    ativos_idx: dict[str, dict] = {}
    for a in desvio_atual["por_ativo"]:
        chave = (a.get("ticker") or a.get("nome", "")).upper()
        ativos_idx[chave] = dict(a)

    # ------------------------------------------------------------------
    # 2. Ler alvos e config do banco
    # ------------------------------------------------------------------
    with Session(engine) as session:
        alvos_classe_rows = session.exec(select(AlvoClasse)).all()
        alvos_ativo_rows = session.exec(select(AlvoAtivo)).all()
        cfg = session.exec(select(ConfigRebalanceamento)).first()

    alvos_classe = {a.classe.value: a.percentual for a in alvos_classe_rows}
    alvos_ativo = {a.identificador.upper(): a.percentual for a in alvos_ativo_rows}

    # ------------------------------------------------------------------
    # 3. Aplicar operações hipotéticas em cópia do snapshot
    # ------------------------------------------------------------------
    ativos_hip = {k: dict(v) for k, v in ativos_idx.items()}
    valor_total_hip = valor_total_atual
    ops_aplicadas: list[str] = []
    avisos: list[str] = []

    for op in operacoes:
        acao = op.get("acao", "").lower()
        ticker = (op.get("ticker") or "").upper()
        nome = op.get("nome") or ticker or "Ativo"
        classe = op.get("classe", ClasseAtivo.ACAO.value)
        qtde = float(op.get("quantidade", 0))
        preco = float(op.get("preco", 0))

        if qtde <= 0 or preco <= 0:
            avisos.append(f"Operação ignorada (quantidade ou preço inválido): {op}")
            continue

        valor_op = round(qtde * preco, 2)
        chave = ticker if ticker else nome.upper()

        if acao == "comprar":
            if chave in ativos_hip:
                ativos_hip[chave]["valor"] = round(ativos_hip[chave]["valor"] + valor_op, 2)
            else:
                ativos_hip[chave] = {
                    "ticker": ticker or None,
                    "nome": nome,
                    "classe": classe,
                    "valor": valor_op,
                    "source": "proposta",
                    "as_of": datetime.now(timezone.utc).isoformat(),
                    "is_live": False,
                }
            valor_total_hip += valor_op
            ops_aplicadas.append(
                f"Compra {qtde:g}x {ticker or nome} @ R$ {preco:.2f} → +R$ {valor_op:,.2f}"
            )

        elif acao == "vender":
            if chave not in ativos_hip:
                avisos.append(f"'{ticker or nome}' não está na carteira — venda ignorada")
                continue
            val_posicao = ativos_hip[chave]["valor"]
            if valor_op > val_posicao + 0.01:
                avisos.append(
                    f"Venda de '{ticker or nome}' (R$ {valor_op:,.2f}) excede a posição "
                    f"(R$ {val_posicao:,.2f}) — ajustado ao total da posição"
                )
                valor_op = val_posicao
            ativos_hip[chave]["valor"] = round(max(0.0, val_posicao - valor_op), 2)
            valor_total_hip -= valor_op
            ops_aplicadas.append(
                f"Venda {qtde:g}x {ticker or nome} @ R$ {preco:.2f} → -R$ {valor_op:,.2f}"
            )
        else:
            avisos.append(f"Ação desconhecida '{acao}' — use 'comprar' ou 'vender'")

    if valor_total_hip <= 0:
        return tool_error("Valor total hipotético seria zero ou negativo após as operações.")

    # ------------------------------------------------------------------
    # 4. Alocação hipotética por classe
    # ------------------------------------------------------------------
    valores_classe_hip: dict[str, float] = {}
    fracao_liquida_val = 0.0

    for a in ativos_hip.values():
        if a["valor"] <= 0:
            continue
        c = a["classe"]
        valores_classe_hip[c] = valores_classe_hip.get(c, 0.0) + a["valor"]
        try:
            if ClasseAtivo(c) in _CLASSES_LIQUIDAS:
                fracao_liquida_val += a["valor"]
        except ValueError:
            pass

    fracao_liquida_pct = round(fracao_liquida_val / valor_total_hip * 100, 1)

    todas_classes = sorted(set(list(alvos_classe.keys()) + list(valores_classe_hip.keys())))
    por_classe = []
    for classe in todas_classes:
        val_hip = valores_classe_hip.get(classe, 0.0)
        pct_hip = round(val_hip / valor_total_hip * 100, 2)
        # Classe sem alvo cadastrado (ex.: CAIXA) tem alvo indefinido, não alvo 0% —
        # mesmo tratamento de calcular_desvio, para não inventar desvio contra zero.
        alvo_pct = alvos_classe.get(classe)

        val_atual = sum(a["valor"] for a in ativos_idx.values() if a.get("classe") == classe)
        pct_atual = round(val_atual / valor_total_atual * 100, 2) if valor_total_atual > 0 else 0.0

        por_classe.append({
            "classe": classe,
            "valor_hip": round(val_hip, 2),
            "percentual_hip": pct_hip,
            "percentual_atual": pct_atual,
            "delta_pp": round(pct_hip - pct_atual, 2),
            "percentual_alvo": alvo_pct,
            "desvio_pp_hip": round(pct_hip - alvo_pct, 2) if alvo_pct is not None else None,
            "desvio_reais_hip": (
                round(val_hip - (alvo_pct / 100 * valor_total_hip), 2)
                if alvo_pct is not None else None
            ),
            "fora_da_banda_hip": (
                _fora_da_banda(pct_hip, alvo_pct, cfg) if cfg and alvo_pct else None
            ),
            "sem_alvo_definido": classe not in alvos_classe,
        })

    # ------------------------------------------------------------------
    # 5. Alocação hipotética por ativo
    # ------------------------------------------------------------------
    por_ativo = []
    for chave, a in ativos_hip.items():
        if a["valor"] <= 0:
            continue
        ticker_up = (a.get("ticker") or "").upper()
        alvo_pct = alvos_ativo.get(ticker_up) if ticker_up else None
        pct_hip = round(a["valor"] / valor_total_hip * 100, 2)
        pct_atual = round(ativos_idx.get(chave, {}).get("valor", 0) / valor_total_atual * 100, 2) if valor_total_atual > 0 else 0.0

        por_ativo.append({
            "ticker": a.get("ticker"),
            "nome": a.get("nome"),
            "classe": a.get("classe"),
            "valor_hip": round(a["valor"], 2),
            "percentual_hip": pct_hip,
            "percentual_atual": pct_atual,
            "delta_pp": round(pct_hip - pct_atual, 2),
            "percentual_alvo": alvo_pct,
            "desvio_pp_hip": round(pct_hip - alvo_pct, 2) if alvo_pct is not None else None,
            "fora_da_banda_hip": (
                _fora_da_banda(pct_hip, alvo_pct, cfg) if cfg and alvo_pct is not None else None
            ),
            "source": a.get("source", "proposta"),
        })

    por_ativo.sort(key=lambda x: -x["valor_hip"])

    logger.info(
        "proposta_rebalanceamento: R$%.2f → R$%.2f | líquido=%.1f%% | %d op(s)",
        valor_total_atual, valor_total_hip, fracao_liquida_pct, len(ops_aplicadas),
    )

    return {
        "data_analise": datetime.now(timezone.utc).isoformat(),
        "operacoes_aplicadas": ops_aplicadas,
        "avisos": avisos,
        "snapshot_atual": {
            "valor_total": valor_total_atual,
            "fracao_ao_vivo_pct": snap["fracao_ao_vivo_pct"],
        },
        "snapshot_hipotetico": {
            "valor_total": round(valor_total_hip, 2),
            "delta_total": round(valor_total_hip - valor_total_atual, 2),
            "fracao_liquida_pct": fracao_liquida_pct,
        },
        "por_classe": por_classe,
        "por_ativo": por_ativo,
        "nota": (
            "Simulação hipotética — não altera o banco. "
            "Preços dos ativos existentes: snapshot ao vivo. "
            "Preços das operações hipotéticas: fornecidos nas operações."
        ),
    }
