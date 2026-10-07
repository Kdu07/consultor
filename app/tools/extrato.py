"""
Tool importar_extrato — lê o extrato XLSX do BTG enviado pela UI.

Guardrail 4 (PLANO §3, §10): esta tool APENAS retorna o preview. Nunca grava nada.
A gravação acontece numa tool separada (gravar_posicoes) somente após confirmação
explícita do usuário no turno seguinte.

O arquivo em si nunca chega ao modelo: o upload (POST /extrato/upload) parseia no
servidor e deixa o preview em app/tools/extrato_staging.py — ver docs/PLANO_XLSX.md §3.
"""
import logging
from typing import Sequence

from . import extrato_staging
from .btg_xlsx_parser import ExtratoParsed
from .desempenho import extrair_mes
from .lancamentos import Regra
from .schemas import tool_error

logger = logging.getLogger(__name__)


def resumo_validacao(validacao: dict | None) -> dict | None:
    """
    Versão compacta de payload["validacao"] (app/tools/extrato_validacao.py) para o
    preview e para os itens do lote: o preview vai INTEIRO ao contexto do modelo, então
    a lista completa de checks fica de fora — só o veredito e as mensagens que o modelo
    (ou a UI) deve repetir ao usuário.
    """
    if not validacao:
        return None
    checks = validacao.get("checks") or []
    return {
        "veredito": validacao.get("veredito"),
        "erros": list(validacao.get("erros") or []),
        "avisos": list(validacao.get("avisos") or []),
        "n_checks_ok": sum(1 for c in checks if (c or {}).get("severidade") == "ok"),
    }


def montar_preview(
    extrato: ExtratoParsed,
    arquivo: str,
    regras: Sequence[Regra] = (),
    validacao: dict | None = None,
) -> dict:
    """
    Converte o resultado do parser no preview consumido pelo agente e pela UI.
    Formato compatível com o argumento `posicoes` de gravar_posicoes.
    `regras` são as classificações de lançamento do dono (a rentabilidade do mês depende
    delas para separar aporte de rendimento).
    `validacao` é o payload["validacao"] de anexar_validacao — entra compactado no
    preview (resumo_validacao); quem decide bloquear é gravar_posicoes, pelo bruto.
    """
    mes = extrair_mes(extrato.data_referencia, extrato.to_dict(), regras)
    posicoes = [p.to_dict() for p in extrato.posicoes]
    total = sum(p.valor_mercado for p in extrato.posicoes)

    por_classe: dict[str, dict] = {}
    for p in extrato.posicoes:
        acc = por_classe.setdefault(p.classe, {"qtd_ativos": 0, "valor_total": 0.0})
        acc["qtd_ativos"] += 1
        acc["valor_total"] += p.valor_mercado
    for acc in por_classe.values():
        acc["valor_total"] = round(acc["valor_total"], 2)

    preview: dict = {
        "posicoes": posicoes,
        "total_posicoes": len(posicoes),
        "total_valor_mercado": round(total, 2),
        "data_referencia": extrato.data_referencia,
        "resumo_por_classe": por_classe,
        "source": "extrato_btg_xlsx",
        "arquivo": arquivo,
        # Só a conferência das posições: as do razão e das movimentações (parser v2) ficam
        # no extrato arquivado, fora do preview que vai inteiro para o modelo.
        "checagem_totais": {
            k: v for k, v in (extrato.checagem or {}).items()
            if k not in ("conta_corrente", "movimentacao_rv")
        },
        "proventos_do_mes": _resumo_proventos(extrato),
        "aluguel_ativo": extrato.aluguel,
        "valores_em_transito": _resumo_transito(extrato),
        "comparativo_mes_anterior": _comparativo(extrato),
        "rentabilidade_do_mes": _rentabilidade(mes),
    }
    if extrato.linhas_ignoradas:
        preview["linhas_ignoradas"] = extrato.linhas_ignoradas

    # Campos ADITIVOS do plano "Confiabilidade" — nenhum campo existente muda de nome.
    meta = (extrato.sumario or {}).get("meta") or {}
    preview["periodo"] = {
        "inicio": meta.get("periodo_inicio"),
        "fim": extrato.data_referencia,
        # Mensal = 1º ao último dia do mesmo mês civil — a mesma régua do motor de
        # desempenho (extrair_mes/_periodo_mensal), que marca o resto como parcial.
        "mensal": mes["status"] != "periodo_parcial",
    }
    total_sumario = ((extrato.sumario or {}).get("atual") or {}).get("total") or {}
    preview["patrimonio"] = {
        "valor_posicoes": round(total, 2),                    # Σ posições, sem trânsito
        "patrimonio_bruto": total_sumario.get("bruto"),       # Total Bruto do Sumário
        "saldo_liquido_btg": total_sumario.get("liquido"),    # o número do app BTG
        "nota": (
            "Três grandezas distintas: valor_posicoes exclui valores em trânsito; "
            "patrimonio_bruto é o Total Bruto do Sumário; saldo_liquido_btg é o que o "
            "app do BTG mostra."
        ),
    }
    compacto = resumo_validacao(validacao)
    if compacto is not None:
        preview["validacao"] = compacto

    preview["aviso"] = _montar_aviso(extrato, mes, compacto)
    return preview


def _rentabilidade(mes: dict) -> dict:
    """
    Rentabilidade do mês descontados aportes e resgates — sem CDI (o preview não vai à
    rede; a comparação com benchmarks é da tool desempenho_carteira).
    """
    resultado = {
        "status": mes["status"],
        "pct": mes["rentabilidade_pct"],
        "ganho_rs": mes["ganho"],
        "aportes_rs": mes["aportes"],
        "resgates_rs": mes["resgates"],
        "nao_classificados": mes["nao_classificados"],
    }
    if mes["status"] == "ok":
        resultado["nota"] = (
            "Rentabilidade bruta do mês (Modified Dietz), descontados os aportes e resgates "
            "do razão da conta corrente."
        )
    elif mes["status"] == "provisorio":
        resultado["nota"] = (
            "Provisória: há lançamentos da conta que não foram reconhecidos como aporte, "
            "resgate ou movimentação interna, ou o razão não fecha. Contei os pendentes como "
            "internos; o número muda se algum for aporte ou resgate."
        )
    elif mes["status"] == "periodo_parcial":
        resultado["nota"] = "O extrato não cobre um mês civil inteiro — fica fora da série mensal."
    else:
        resultado["nota"] = "Não foi possível calcular a rentabilidade deste mês."
    return resultado


def _resumo_proventos(extrato: ExtratoParsed) -> dict:
    total_liquido = sum(p.get("valor_liquido") or 0.0 for p in extrato.proventos)
    return {
        "total_liquido": round(total_liquido, 2),
        "quantidade": len(extrato.proventos),
        "itens": extrato.proventos,
    }


def _resumo_transito(extrato: ExtratoParsed) -> dict:
    total = sum(v["valor"] for v in extrato.valores_em_transito)
    return {
        "total": round(total, 2),
        "itens": extrato.valores_em_transito,
        "nota": "Ainda não liquidado — fora da carteira, não entra no caixa.",
    }


def _comparativo(extrato: ExtratoParsed) -> dict | None:
    """Saldo bruto do mês atual vs. mês anterior, direto da aba Sumario."""
    atual = (extrato.sumario or {}).get("atual") or {}
    anterior = (extrato.sumario or {}).get("anterior") or {}
    v_atual = (atual.get("total") or {}).get("bruto")
    v_anterior = (anterior.get("total") or {}).get("bruto")
    if v_atual is None or v_anterior is None:
        return None
    variacao = v_atual - v_anterior
    return {
        "data_atual": atual.get("data"),
        "data_anterior": anterior.get("data"),
        "saldo_bruto_atual": round(v_atual, 2),
        "saldo_bruto_anterior": round(v_anterior, 2),
        "variacao_reais": round(variacao, 2),
        "variacao_pct": round(variacao / v_anterior * 100, 2) if v_anterior else None,
        "nota": (
            "Variação de saldo do extrato — inclui aportes, retiradas e proventos, "
            "não é rentabilidade da carteira. A rentabilidade do mês, descontados aportes "
            "e resgates, está em rentabilidade_do_mes."
        ),
    }


def _montar_aviso(extrato: ExtratoParsed, mes: dict, validacao: dict | None = None) -> str:
    partes = [
        "PREVIEW — nenhuma posição foi salva. "
        "Confirme com 'sim' para que eu grave estas posições na carteira."
    ]
    val = validacao or {}
    if val.get("erros"):
        partes.append(
            "VALIDAÇÃO REPROVOU o extrato — a gravação será recusada: "
            + " | ".join(val["erros"])
        )
    elif val.get("avisos"):
        partes.append("Avisos da validação (não bloqueiam): " + " | ".join(val["avisos"]))
    if mes["status"] == "periodo_parcial":
        partes.append(
            "Extrato de período parcial/não-mensal: atualiza a carteira de hoje, entra "
            "no histórico como parcial e NÃO vira o mês na série de desempenho."
        )
    checagem = extrato.checagem or {}
    if not checagem.get("ok") and checagem.get("aviso"):
        partes.append("ATENÇÃO: " + checagem["aviso"])
    if extrato.linhas_ignoradas:
        partes.append(
            f"{len(extrato.linhas_ignoradas)} linha(s) do extrato não foram interpretadas — "
            "veja 'linhas_ignoradas' e confira se falta alguma posição."
        )
    if mes["nao_classificados"]:
        partes.append(
            f"{mes['nao_classificados']} lançamento(s) da conta corrente não foram "
            "reconhecidos como aporte, resgate ou movimentação interna: a rentabilidade do "
            "mês fica provisória até o usuário classificá-los na tela Histórico › Extratos."
        )
    conta = checagem.get("conta_corrente") or {}
    if conta.get("ok") is False and conta.get("aviso"):
        partes.append("ATENÇÃO: " + conta["aviso"])
    return " ".join(partes)


async def tool_importar_extrato() -> dict:
    """
    Retorna o preview do extrato XLSX que o usuário enviou pela UI.
    NÃO salva nenhuma posição.
    """
    estado = extrato_staging.get()
    if not estado:
        return tool_error(
            "Nenhum extrato foi enviado ainda. Peça ao usuário para clicar em "
            "'Importar extrato BTG' na interface e selecionar o arquivo XLSX da conta "
            "de investimento."
        )

    preview = dict(estado["preview"])
    preview["recebido_em"] = estado["recebido_em"]

    logger.info(
        "importar_extrato: preview de '%s' devolvido (%d posicoes, ref=%s)",
        estado.get("arquivo"), preview.get("total_posicoes"), preview.get("data_referencia"),
    )
    return preview
