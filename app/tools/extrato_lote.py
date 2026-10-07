"""
Upload em lote de extratos (docs/PLANO_HISTORICO.md, §3.8 e Bloco 5).

O lote serve para preencher o histórico com meses que NÃO mexem na carteira: confirmar só
arquiva (ExtratoImportado) e nunca toca em Posicao. Mês mais novo que a carteira continua
pelo chat — preview do agente, "sim", gravar_posicoes (guardrail 4). A confirmação reavalia
tudo contra o corte do momento: entre o envio e o clique, outro mês pode ter sido importado
pelo chat.

Status de cada arquivo:
  novo                   anterior ao corte, mês ainda não arquivado          → arquivável
  substitui              anterior ao corte, mês já arquivado                 → arquivável
  reenvio_do_atual       é o mês do corte e as posições batem com as atuais  → arquivável
  diverge_da_carteira    é o mês do corte, mas as posições não batem         → pelo chat
  mais_novo_que_carteira posterior ao corte (ou carteira sem corte)          → pelo chat
  periodo_nao_mensal     o extrato não cobre um mês civil inteiro            → recusado
  duplicado_no_lote      o mesmo mês veio duas vezes no lote                 → recusado
  erro                   o arquivo não foi lido                              → recusado

Validação de invariantes (plano "Confiabilidade", parser v3): cada item carrega
`validacao` (resumo compacto de anexar_validacao) e o payload arquivado é o bruto COM a
chave `validacao`. Veredito "erro" → selecionavel=False e mensagem = primeiro erro;
"aviso" → selecionável, desmarcado por padrão. `confirmar` reavalia e herda o bloqueio
(motivo "validacao_erro").

Staging em memória, separado do slot do chat (extrato_staging): um lote por vez, expira em
uma hora. Do XLSX só fica o que o parser extraiu — o binário é descartado no upload.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlmodel import Session, select

from ..models.extrato import ExtratoImportado
from ..models.posicao import Posicao
from .btg_xlsx_parser import ExtratoParsed
from .desempenho import extrair_mes
from .extrato import montar_preview, resumo_validacao
from .extrato_arquivo import arquivar_extrato, data_de_corte
from .extrato_validacao import anexar_validacao
from .lancamentos import Regra

logger = logging.getLogger(__name__)

MAX_ARQUIVOS = 24
VALIDADE = timedelta(hours=1)
TOLERANCIA_QUANTIDADE = 1e-6
TOLERANCIA_VALOR = 1.00

ARQUIVAVEIS = frozenset({"novo", "substitui", "reenvio_do_atual"})

_lote: Optional[dict] = None
_trava = threading.Lock()


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------

def avaliar(
    session: Session,
    recebidos: Sequence[tuple[str, Optional[ExtratoParsed], Optional[str]]],
    regras: Sequence[Regra] = (),
) -> list[dict]:
    """
    `recebidos` = (arquivo, extrato parseado ou None, erro). Devolve um item por arquivo,
    na ordem. Os campos que começam com '_' ficam só no servidor.
    """
    corte = data_de_corte(session)
    arquivados = {r.data_referencia: r for r in session.exec(select(ExtratoImportado)).all()}
    carteira = {
        p.chave_externa: (p.quantidade, p.valor_mercado)
        for p in session.exec(select(Posicao).where(Posicao.ativo == True)).all()  # noqa: E712
        if p.chave_externa
    }
    vistos: set[date] = set()
    return [
        _avaliar_item(arquivo, extrato, erro, corte, arquivados, carteira, vistos, regras,
                      session)
        for arquivo, extrato, erro in recebidos
    ]


def _avaliar_item(
    arquivo: str,
    extrato: Optional[ExtratoParsed],
    erro: Optional[str],
    corte: Optional[date],
    arquivados: dict[date, ExtratoImportado],
    carteira: dict[str, tuple[float, Optional[float]]],
    vistos: set[date],
    regras: Sequence[Regra],
    session: Session,
) -> dict:
    item: dict[str, Any] = {
        "arquivo": arquivo,
        "data_referencia": None,
        "status": "erro",
        "selecionavel": False,
        "selecionado_padrao": False,
        "patrimonio": None,
        "total_posicoes": None,
        "lancamentos": None,
        "nao_classificados": None,
        "checagem_ok": None,
        "checagem_conta_ok": None,
        "rentabilidade_pct": None,
        "completa_lancamentos": False,
        "mensagem": erro,
        "avisos": [],
        "validacao": None,
        "_extrato": extrato,
    }
    if extrato is None:
        return item

    preview = montar_preview(extrato, arquivo, regras)
    # O payload que o lote ARQUIVA é o de anexar_validacao (com `validacao`), nunca o
    # to_dict() cru — o histórico precisa do veredito tanto quanto o chat (V7 incluso,
    # a session já está na mão).
    bruto = anexar_validacao(extrato, session)
    validacao = resumo_validacao(bruto.get("validacao"))
    mes = extrair_mes(extrato.data_referencia, bruto, regras)
    ref = date.fromisoformat(extrato.data_referencia)
    checagem = extrato.checagem or {}
    item.update({
        "data_referencia": ref.isoformat(),
        "patrimonio": mes["patrimonio_fim"],
        "total_posicoes": preview["total_posicoes"],
        "lancamentos": len(extrato.lancamentos_conta),
        "nao_classificados": mes["nao_classificados"],
        "checagem_ok": checagem.get("ok"),
        "checagem_conta_ok": (checagem.get("conta_corrente") or {}).get("ok"),
        "rentabilidade_pct": mes["rentabilidade_pct"],
        "mensagem": None,
        "validacao": validacao,
        "_preview": preview,
        "_bruto": bruto,
    })
    existente = arquivados.get(ref)

    if mes["status"] == "periodo_parcial":
        item["status"] = "periodo_nao_mensal"
        inicio = ((bruto.get("sumario") or {}).get("meta") or {}).get("periodo_inicio")
        item["mensagem"] = (
            f"O extrato cobre de {_data_br(inicio)} a {_data_br(ref)}, não um mês inteiro. "
            "O histórico mensal só aceita o extrato do mês completo."
        )
    elif ref in vistos:
        item["status"] = "duplicado_no_lote"
        item["mensagem"] = "Este mês já veio em outro arquivo do mesmo lote."
    elif corte is None or ref > corte:
        item["status"] = "mais_novo_que_carteira"
        item["mensagem"] = (
            "Mais novo que a carteira atual: importe pelo chat, que confere as posições "
            "e atualiza a carteira."
        )
    elif ref == corte:
        if _posicoes_batem(bruto, existente, carteira):
            item["status"] = "reenvio_do_atual"
        else:
            item["status"] = "diverge_da_carteira"
            item["mensagem"] = (
                "É o mês que a carteira reflete, mas as posições não batem com as atuais. "
                "Para corrigir a carteira, importe pelo chat."
            )
    else:
        item["status"] = "substitui" if existente else "novo"
    vistos.add(ref)

    item["selecionavel"] = item["status"] in ARQUIVAVEIS
    if existente is not None and item["selecionavel"]:
        item["completa_lancamentos"] = _versao(existente) < 2
    padrao = item["selecionavel"] and (
        existente is None or item["completa_lancamentos"]
    )
    if item["selecionavel"] and item["checagem_ok"] is False:
        item["avisos"].append("O total das posições não bate com o Sumário do extrato.")
        padrao = False
    if item["selecionavel"] and item["checagem_conta_ok"] is False:
        item["avisos"].append("O razão da conta corrente não fecha — a rentabilidade do mês fica provisória.")
    if existente is not None and item["selecionavel"] and not item["completa_lancamentos"]:
        item["avisos"].append("O mês já está arquivado com os lançamentos da conta: arquivar de novo só substitui.")
    # Validação por gravidade: "erro" (> R$ 1,00) bloqueia o item; "aviso" deixa
    # selecionável mas desmarcado — mesmo tratamento da checagem que falha, acima.
    veredito = (validacao or {}).get("veredito")
    if item["selecionavel"] and veredito == "erro":
        item["selecionavel"] = False
        padrao = False
        item["mensagem"] = (validacao.get("erros") or ["O extrato reprovou na validação de invariantes."])[0]
    elif item["selecionavel"] and veredito == "aviso":
        item["avisos"].extend(validacao.get("avisos") or [])
        padrao = False
    item["selecionado_padrao"] = padrao
    return item


def _data_br(valor: Any) -> str:
    """'2026-08-10' (ou date) → '10/08/2026'; texto ilegível passa como veio."""
    try:
        d = valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])
    except ValueError:
        return str(valor)
    return d.strftime("%d/%m/%Y")


def _versao(registro: ExtratoImportado) -> int:
    try:
        return int(json.loads(registro.payload_json).get("versao_parser") or 1)
    except (ValueError, AttributeError):
        return 1


def _posicoes_batem(
    bruto: dict,
    existente: Optional[ExtratoImportado],
    carteira: dict[str, tuple[float, Optional[float]]],
) -> bool:
    """As posições do extrato são as do arquivo daquela data (ou, sem ele, as da carteira)?"""
    novas = {
        p.get("chave_externa"): (float(p.get("quantidade") or 0.0), p.get("valor_mercado"))
        for p in bruto.get("posicoes") or [] if p.get("chave_externa")
    }
    if existente is not None:
        try:
            antigas_lista = json.loads(existente.payload_json).get("posicoes") or []
        except (ValueError, AttributeError):
            return False
        referencia = {
            p.get("chave_externa"): (float(p.get("quantidade") or 0.0), p.get("valor_mercado"))
            for p in antigas_lista if p.get("chave_externa")
        }
    else:
        referencia = carteira
    if set(novas) != set(referencia):
        return False
    for chave, (qtd, valor) in novas.items():
        qtd_ref, valor_ref = referencia[chave]
        if abs(qtd - float(qtd_ref or 0.0)) > TOLERANCIA_QUANTIDADE:
            return False
        if valor is not None and valor_ref is not None and abs(float(valor) - float(valor_ref)) > TOLERANCIA_VALOR:
            return False
    return True


# ---------------------------------------------------------------------------
# Confirmação
# ---------------------------------------------------------------------------

def confirmar(
    session: Session,
    lote: dict,
    datas: Sequence[str],
    regras: Sequence[Regra] = (),
) -> dict:
    """
    Arquiva os meses pedidos que continuam arquiváveis — reavaliando contra o banco de
    agora — numa transação só. Nunca toca em Posicao.
    """
    itens = avaliar(
        session,
        [(i["arquivo"], i["_extrato"], i["mensagem"] if i["_extrato"] is None else None) for i in lote["itens"]],
        regras,
    )
    por_data = {i["data_referencia"]: i for i in itens if i["data_referencia"]}
    agora = datetime.now(timezone.utc)
    arquivados: list[dict] = []
    recusados: list[dict] = []

    for data_iso in dict.fromkeys(datas):   # sem repetir, na ordem pedida
        item = por_data.get(data_iso)
        if item is None:
            recusados.append({"data_referencia": data_iso, "motivo": "nao_esta_no_lote",
                              "mensagem": "Este mês não está no lote enviado."})
            continue
        if item["status"] not in ARQUIVAVEIS:
            recusados.append({"data_referencia": data_iso, "motivo": item["status"],
                              "mensagem": item["mensagem"]})
            continue
        if not item["selecionavel"]:
            # Status arquivável, mas a validação (reavaliada agora) reprovou o extrato:
            # o bloqueio do envio é herdado pela confirmação.
            recusados.append({"data_referencia": data_iso, "motivo": "validacao_erro",
                              "mensagem": item["mensagem"]})
            continue
        registro, novo = arquivar_extrato(
            session, item["_preview"], item["_bruto"], item["arquivo"],
            date.fromisoformat(data_iso), agora,
        )
        arquivados.append({"data_referencia": data_iso, "acao": "criado" if novo else "atualizado"})

    session.commit()
    logger.info("lote %s: %d mes(es) arquivado(s), %d recusado(s)",
                lote["id"], len(arquivados), len(recusados))
    return {"arquivados": arquivados, "recusados": recusados, "carteira_alterada": False}


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def guardar(itens: list[dict]) -> dict:
    global _lote
    with _trava:
        _lote = {
            "id": "lote_" + secrets.token_hex(4),
            "criado_em": datetime.now(timezone.utc),
            "itens": itens,
        }
        return _lote


def obter(lote_id: str) -> Optional[dict]:
    global _lote
    with _trava:
        if _lote is None or _lote["id"] != lote_id:
            return None
        if datetime.now(timezone.utc) - _lote["criado_em"] > VALIDADE:
            _lote = None
            return None
        return _lote


def descartar(lote_id: Optional[str] = None) -> None:
    global _lote
    with _trava:
        if lote_id is None or (_lote is not None and _lote["id"] == lote_id):
            _lote = None


def para_resposta(lote: dict, corte: Optional[date]) -> dict:
    return {
        "id": lote["id"],
        "criado_em": lote["criado_em"].isoformat(),
        "data_corte": corte.isoformat() if corte else None,
        "itens": [{k: v for k, v in i.items() if not k.startswith("_")} for i in lote["itens"]],
    }
