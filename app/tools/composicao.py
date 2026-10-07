"""
Composição do desempenho por classe e por ativo (docs/PLANO_HISTORICO.md, "Composição" e
Bloco 9) — funções puras, como desempenho.py.

Para cada mês M com o arquivo de M−1, cada papel (chave_externa) ganha:

  resultado R$  = V1 − V0 − compras + vendas + renda
  % do papel    = (P_fim + renda por unidade) / P_ref − 1        (TWR por preço unitário)

e cada classe, um Modified Dietz sobre os valores somados dos seus papéis (compras entram,
vendas e renda saem). O papel não usa Dietz porque, com V0 = 0 (comprado no mês) ou saída
total, a base quase zera e o percentual explode: R$ 1.000 comprados no dia 30 que fecham a
R$ 1.010 dariam ~31% "no mês". O preço unitário não depende de fluxo nenhum. A classe pode
cair no mesmo buraco (primeira compra de FII no fim do mês) — aí fica sem percentual.

De onde vem cada fluxo do papel:
  - compra/venda de RV     → movimentação de RV do extrato (valor líquido, já com custos)
  - compra de Tesouro/RF   → lote do Detalhamento com aquisição dentro do mês
  - resgate de Tesouro/RF  → linha RESGATE_RF do razão que cita o título; sem ela, estimado
                             pela quantidade que sumiu × preço médio dos dois fechamentos
  - renda                  → proventos da movimentação de RV; cupom e aluguel que o razão
                             atribui ao papel (lancamentos.ativo_ref)

Quantidade que muda sem negociação: se o preço andou na proporção inversa (desdobramento,
grupamento, bonificação), o preço de referência é ajustado sozinho. Se não, é pendência que
o dono resolve com uma regra `ativo_mes` — evento societário, ou ativo trazido/levado de
outra corretora; este vira aporte/resgate também no total (transferencias_de_ativos).

Conferência do mês: ganho do total = Σ resultados dos papéis + rendimento do saldo + custos
+ outros lançamentos internos + renda sem papel + variação dos valores em trânsito +
resíduo. Resíduo acima de max(R$ 5; 0,05% do patrimônio) vira aviso: algum fluxo de papel
não foi visto (compra de Tesouro sem lote no extrato, por exemplo).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable, Optional, Sequence

from .btg_xlsx_parser import _norm
from .desempenho import _data, _ja_contado, _num, _pct, _r2, dietz, mes_de
from .lancamentos import (
    ALUGUEL,
    APORTE_EM_ATIVOS,
    EVENTO_SOCIETARIO,
    IMPOSTO,
    OUTRO_INTERNO,
    PROVENTO,
    RENDIMENTO_CAIXA,
    RESGATE_EM_ATIVOS,
    RESGATE_RF,
    TAXA,
    Regra,
    ativo_ref,
    classificar_mes,
)

TOLERANCIA_QUANTIDADE = 1e-6
# Desdobramento reconhecido sozinho: desfeito o fator, o preço fica nesta faixa do anterior
# E mais perto dele do que sem desfazer (10 ações a mais com o preço parado é outra coisa).
FAIXA_EVENTO = (0.7, 1.3)
# Classe sem percentual quando a base do Dietz é pequena perto do tamanho da classe
BASE_MINIMA_CLASSE = 0.25
# Resíduo da conferência que vira aviso: max(R$ 5; 0,05% do patrimônio do início)
RESIDUO_MINIMO = 5.0
RESIDUO_RELATIVO = 0.0005

STATUS_COM_NUMERO = ("ok", "estimado")
_TRANSFERENCIAS = (APORTE_EM_ATIVOS, RESGATE_EM_ATIVOS)


# ---------------------------------------------------------------------------
# Leitura do payload
# ---------------------------------------------------------------------------

def _valor(item: dict) -> float:
    valor = _num(item.get("valor_liquido"))
    if valor is None:
        valor = _num(item.get("valor_bruto"))
    return valor or 0.0


def _operacao(item: dict) -> str:
    """COMPRA | VENDA | outra — arquivos v1 não trazem `operacao`, só o texto da transação."""
    if item.get("operacao"):
        return item["operacao"]
    n = _norm(item.get("transacao"))
    if n.startswith("compra"):
        return "COMPRA"
    if n.startswith("venda"):
        return "VENDA"
    return "OUTRO"


def _posicoes(payload: Optional[dict]) -> dict[str, dict]:
    """Papéis do extrato por chave_externa — o caixa fica de fora."""
    return {
        p["chave_externa"]: p
        for p in (payload or {}).get("posicoes") or []
        if p.get("chave_externa") and p.get("classe") != "CAIXA"
    }


def _caixa(payload: Optional[dict]) -> float:
    return sum(_num(p.get("valor_mercado")) or 0.0
               for p in (payload or {}).get("posicoes") or [] if p.get("classe") == "CAIXA")


def _transito(payload: dict, periodo: str) -> float:
    mercados = (((payload.get("sumario") or {}).get(periodo) or {}).get("mercados")) or {}
    for nome, valores in mercados.items():
        if _norm(nome).startswith("valores em transito"):
            return _num((valores or {}).get("bruto")) or 0.0
    return 0.0


def _q(p: Optional[dict]) -> float:
    return (_num(p.get("quantidade")) or 0.0) if p else 0.0


def _v(p: Optional[dict]) -> float:
    return (_num(p.get("valor_mercado")) or 0.0) if p else 0.0


def _preco(p: Optional[dict]) -> Optional[float]:
    """
    Preço unitário = saldo ÷ quantidade: é o preço de fechamento (ou o PU do título) sem o
    arredondamento da coluna, e mantém o % do papel coerente com o resultado em R$.
    """
    if not p:
        return None
    if _q(p) > TOLERANCIA_QUANTIDADE:
        return _v(p) / _q(p)
    return _num(p.get("preco_fechamento"))


def _regra_ativo(regras: Sequence[Regra], ref: Optional[str], chave: str) -> Optional[str]:
    for r in regras:
        if r.escopo == "ativo_mes" and r.data_referencia == ref and r.padrao == chave:
            return r.tipo
    return None


def _parece_evento(p0: Optional[float], p1: Optional[float], fator: float) -> bool:
    """O preço novo, desfeito o fator de quantidade, volta para perto do antigo?"""
    if not p0 or not p1 or fator <= 0:
        return False
    com, sem = p1 * fator / p0, p1 / p0
    return FAIXA_EVENTO[0] <= com <= FAIXA_EVENTO[1] and abs(math.log(com)) < abs(math.log(sem))


# ---------------------------------------------------------------------------
# Um mês
# ---------------------------------------------------------------------------

def composicao_mes(
    ref: Optional[str],
    payload: dict,
    payload_anterior: Optional[dict],
    data_ini: date,
    data_fim: date,
    regras: Sequence[Regra] = (),
    ganho_total: Optional[float] = None,
    v_ini_total: Optional[float] = None,
) -> dict:
    """
    Composição do mês cujo extrato tem `data_referencia` = `ref`. Sem o arquivo do mês
    anterior, só o papel que entrou inteiro no mês tem base; os demais saem `sem_base`.
    `ganho_total` (do motor do total) liga a conferência do mês.
    """
    pos0, pos1 = _posicoes(payload_anterior), _posicoes(payload)
    tem_anterior = payload_anterior is not None
    tem_razao = int(payload.get("versao_parser") or 1) >= 2
    classificados = (
        classificar_mes(ref, payload.get("lancamentos_conta") or [], regras) if tem_razao else []
    )
    papeis = {c: pos1.get(c) or pos0.get(c) for c in set(pos0) | set(pos1)}
    titulos = {c: p for c, p in papeis.items() if c.startswith(("TD:", "RF:"))}
    fluxos: dict[str, dict[str, list[dict]]] = {}

    def _fluxo(chave: str, lado: str, quando: Any, valor: float,
               quantidade: Optional[float] = None, origem: str = "extrato") -> None:
        fluxos.setdefault(chave, {"compras": [], "vendas": [], "renda": []})[lado].append(
            {"data": quando, "valor": float(valor), "quantidade": quantidade, "origem": origem}
        )

    # Compras e vendas: RV identifica-se pelo ticker (chave B3); fundos e cripto não têm
    # ticker e já trazem a própria chave_externa (FUNDO:/CRIPTO:) desde o parser v3.
    for m in payload.get("movimentacoes") or []:
        op, ticker, valor = _operacao(m), (m.get("ticker") or "").upper(), abs(_valor(m))
        chave = m.get("chave_externa") or (f"B3:{ticker}" if ticker else None)
        if op in ("COMPRA", "VENDA") and chave and valor:
            quantidade = abs(_num(m.get("quantidade")) or 0.0) or None
            _fluxo(chave, "compras" if op == "COMPRA" else "vendas",
                   m.get("data"), valor, quantidade)

    # Compras de Tesouro/RF: lotes adquiridos dentro do mês
    for lote in payload.get("lotes_rf") or []:
        aquisicao = _data(lote.get("aquisicao"))
        if lote.get("chave_externa") and aquisicao and data_ini < aquisicao <= data_fim:
            _fluxo(lote["chave_externa"], "compras", aquisicao.isoformat(),
                   _num(lote.get("valor_compra")) or 0.0, _num(lote.get("quantidade")))

    # Renda da movimentação (RV pelo ticker; fundo/cripto pela chave_externa)
    proventos = payload.get("proventos") or []
    for p in proventos:
        ticker, valor = (p.get("ticker") or "").upper(), _valor(p)
        chave = p.get("chave_externa") or (f"B3:{ticker}" if ticker else None)
        if chave and valor:
            _fluxo(chave, "renda", p.get("data"), valor, _num(p.get("quantidade")))

    # Razão: o que é do caixa, o que é de um papel. Compra, venda e aplicação no razão são
    # o lado do dinheiro de negociações já vistas acima — não entram de novo.
    conta = {"rendimento": 0.0, "custos": 0.0, "outros": 0.0, "renda_sem_papel": 0.0}
    resgates_soltos: list[dict] = []
    for c in classificados:
        if c.get("externo"):
            continue
        tipo, valor = c["tipo"], float(c["valor"])
        if tipo == RENDIMENTO_CAIXA:
            conta["rendimento"] += valor
        elif tipo in (IMPOSTO, TAXA):
            conta["custos"] += valor
        elif tipo == OUTRO_INTERNO:
            conta["outros"] += valor
        elif tipo == RESGATE_RF and valor > 0:
            chave = ativo_ref(c.get("descricao"), titulos)
            if chave:
                _fluxo(chave, "vendas", c.get("data"), valor, origem="razao")
            else:
                resgates_soltos.append(c)
        elif tipo in (PROVENTO, ALUGUEL):
            if valor <= 0:
                conta["outros"] += valor
            elif not (tipo == PROVENTO and _ja_contado(c, proventos)):
                chave = ativo_ref(c.get("descricao"), papeis)
                if chave:
                    _fluxo(chave, "renda", c.get("data"), valor, origem="razao")
                else:
                    conta["renda_sem_papel"] += valor

    # Resgate que não cita o título: se um só título encolheu sem venda e um só resgate
    # ficou solto, um é do outro.
    def _saiu(chave: str) -> float:
        compras = fluxos.get(chave, {}).get("compras", [])
        return _q(pos0.get(chave)) + sum(x["quantidade"] or 0.0 for x in compras) - _q(pos1.get(chave))

    encolheram = [c for c in titulos
                  if _saiu(c) > TOLERANCIA_QUANTIDADE and not fluxos.get(c, {}).get("vendas")]
    if len(encolheram) == 1 and len(resgates_soltos) == 1:
        r = resgates_soltos.pop()
        _fluxo(encolheram[0], "vendas", r.get("data"), float(r["valor"]), origem="razao")

    meio = (data_ini + (data_fim - data_ini) / 2).isoformat()
    ativos: list[dict] = []
    transferencias: list[tuple[str, float]] = []
    for chave in sorted(set(pos0) | set(pos1) | set(fluxos)):
        papel, transferencia = _papel(
            chave, pos0.get(chave), pos1.get(chave),
            fluxos.get(chave) or {"compras": [], "vendas": [], "renda": []},
            regra=_regra_ativo(regras, ref, chave),
            tem_anterior=tem_anterior, tem_razao=tem_razao, data_fim=data_fim, meio=meio,
        )
        ativos.append(papel)
        if transferencia:
            transferencias.append(transferencia)

    classes = _classes_do_mes(ativos, data_ini, data_fim)
    for a in ativos:
        a.pop("_fluxos", None)

    soma = sum(a["resultado"] for a in ativos if a["resultado"] is not None)
    transito = _transito(payload, "atual") - _transito(payload, "anterior")
    residuo = None
    avisos: list[str] = []
    if (ganho_total is not None and tem_anterior
            and all(a["status"] in STATUS_COM_NUMERO for a in ativos)):
        residuo = ganho_total - (soma + sum(conta.values()) + transito)
        if abs(residuo) > max(RESIDUO_MINIMO, RESIDUO_RELATIVO * (v_ini_total or 0.0)):
            avisos.append("residuo_alto")
    if not tem_anterior:
        avisos.append("sem_mes_anterior")
    if not tem_razao:
        avisos.append("sem_lancamentos")
    if conta["renda_sem_papel"]:
        avisos.append("renda_sem_papel")
    if resgates_soltos:
        avisos.append("resgate_sem_titulo")

    return {
        "mes": mes_de(data_fim),
        "data_referencia": ref,
        "ativos": ativos,
        "classes": classes,
        "caixa": {
            "valor_fim": _r2(_caixa(payload)),
            "rendimento": _r2(conta["rendimento"]),
            "custos": _r2(conta["custos"]),
        },
        "conciliacao": {
            "ganho_total": _r2(ganho_total),
            "ativos": _r2(soma),
            "rendimento_caixa": _r2(conta["rendimento"]),
            "custos": _r2(conta["custos"]),
            "outros": _r2(conta["outros"]),
            "renda_sem_papel": _r2(conta["renda_sem_papel"]),
            "transito": _r2(transito),
            "residuo": _r2(residuo),
        },
        "transferencias": transferencias,
        "avisos": avisos,
    }


def _papel(
    chave: str,
    a0: Optional[dict],
    a1: Optional[dict],
    f: dict[str, list[dict]],
    *,
    regra: Optional[str],
    tem_anterior: bool,
    tem_razao: bool,
    data_fim: date,
    meio: str,
) -> tuple[dict, Optional[tuple[str, float]]]:
    """Resultado de um papel no mês, e o aporte/resgate em ativos que ele gerou (se houve)."""
    eh_titulo = chave.startswith(("TD:", "RF:"))
    info = a1 or a0 or {}
    q0, q1, v0, v1 = _q(a0), _q(a1), _v(a0), _v(a1)
    p0, p1 = _preco(a0), _preco(a1)
    compras, vendas, renda = f["compras"], f["vendas"], f["renda"]
    status, pendencia, aviso = "ok", None, None
    p_ref = p0
    transferencia: Optional[tuple[str, float]] = None

    def _qtd(lista: list[dict]) -> float:
        return sum(x["quantidade"] or 0.0 for x in lista)

    delta = q1 - (q0 + _qtd(compras) - _qtd(vendas))
    if not tem_anterior:
        # Sem o fechamento anterior, só dá para medir o papel que entrou inteiro no mês
        if not (_qtd(compras) > TOLERANCIA_QUANTIDADE and abs(delta) <= TOLERANCIA_QUANTIDADE):
            status = "sem_base"
    elif abs(delta) > TOLERANCIA_QUANTIDADE:
        if regra in _TRANSFERENCIAS:
            preco = p1 if p1 is not None else (p0 or 0.0)
            valor = abs(delta) * preco
            (compras if delta > 0 else vendas).append(
                {"data": data_fim.isoformat(), "valor": valor, "quantidade": abs(delta),
                 "origem": "transferencia"}
            )
            transferencia = (data_fim.isoformat(), valor if delta > 0 else -valor)
            aviso = "trazido_de_outra_corretora" if delta > 0 else "levado_para_outra_corretora"
        elif eh_titulo and delta < 0:
            sem_quantidade = [x for x in vendas if x["quantidade"] is None]
            if sem_quantidade:
                # Resgate do razão: o valor é o do extrato; a quantidade é a que sumiu
                total = sum(x["valor"] for x in sem_quantidade) or 1.0
                for x in sem_quantidade:
                    x["quantidade"] = -delta * x["valor"] / total
            else:
                preco = ((p0 or 0.0) + (p1 if p1 is not None else (p0 or 0.0))) / 2
                vendas.append({"data": meio, "valor": -delta * preco, "quantidade": -delta,
                               "origem": "estimado"})
                status = "estimado"
        elif eh_titulo:
            # Título que cresceu sem lote no mês. Arquivo v1 não tem lotes: reenviar resolve.
            if tem_razao:
                status, pendencia = "pendente", "quantidade_sem_negociacao"
            else:
                status = "indisponivel"
        else:
            q_base = q1 - _qtd(compras) + _qtd(vendas)
            fator = q_base / q0 if q0 > TOLERANCIA_QUANTIDADE and q_base > TOLERANCIA_QUANTIDADE else None
            if fator and (regra == EVENTO_SOCIETARIO or _parece_evento(p0, p1, fator)):
                p_ref = p0 / fator if p0 else None
                aviso = "evento_societario"
            elif regra == EVENTO_SOCIETARIO:
                status, aviso = "indisponivel", "evento_sem_preco_comparavel"
            else:
                status, pendencia = "pendente", "quantidade_sem_negociacao"

    c_valor = sum(x["valor"] for x in compras)
    s_valor = sum(x["valor"] for x in vendas)
    r_valor = sum(x["valor"] for x in renda)
    q_compras, q_vendas = _qtd(compras), _qtd(vendas)

    resultado: Optional[float] = None
    r: Optional[float] = None
    if status in STATUS_COM_NUMERO:
        resultado = v1 - v0 - c_valor + s_valor + r_valor
        if q0 > TOLERANCIA_QUANTIDADE and p_ref:
            base = p_ref
        elif q_compras > TOLERANCIA_QUANTIDADE:
            base = c_valor / q_compras
        else:
            base = None
        if q1 > TOLERANCIA_QUANTIDADE and p1 is not None:
            p_fim = p1
        elif q_vendas > TOLERANCIA_QUANTIDADE:
            p_fim = s_valor / q_vendas
        else:
            p_fim = None
        renda_unidade = 0.0
        for x in renda:
            unidades = x["quantidade"] or q0 or q1 or q_compras
            if unidades:
                renda_unidade += x["valor"] / unidades
        if base and p_fim is not None:
            r = (p_fim + renda_unidade) / base - 1

    desconhecido = status == "sem_base"     # sem o fechamento anterior, o início não é zero: é ignorado
    papel = {
        "chave": chave,
        "ticker": info.get("ticker"),
        "nome": info.get("nome"),
        "classe": info.get("classe") or ("TESOURO" if chave.startswith("TD:") else "OUTRO"),
        "quantidade_ini": None if desconhecido else q0,
        "quantidade_fim": q1,
        "preco_ini": None if desconhecido else _r2(p0),
        "preco_fim": _r2(p1),
        "valor_ini": None if desconhecido else _r2(v0),
        "valor_fim": _r2(v1),
        "compras": _r2(c_valor),
        "vendas": _r2(s_valor),
        "renda": _r2(r_valor),
        "resultado": _r2(resultado),
        "rentabilidade_pct": _pct(r),
        "status": status,
        "pendencia": pendencia,
        "aviso": aviso,
        # Para o Dietz da classe: compras entram, vendas e renda saem
        "_fluxos": [(x["data"], x["valor"]) for x in compras]
                   + [(x["data"], -x["valor"]) for x in vendas]
                   + [(x["data"], -x["valor"]) for x in renda],
    }
    return papel, transferencia


def _classes_do_mes(ativos: Sequence[dict], data_ini: date, data_fim: date) -> list[dict]:
    por_classe: dict[str, list[dict]] = {}
    for a in ativos:
        por_classe.setdefault(a["classe"], []).append(a)
    out = []
    for classe, lista in por_classe.items():
        status = _pior_status(a["status"] for a in lista)
        v0 = sum(a["valor_ini"] or 0.0 for a in lista)
        v1 = sum(a["valor_fim"] or 0.0 for a in lista)
        r = None
        aviso = None
        if status in STATUS_COM_NUMERO:
            r, _, base = dietz(v0, v1, [x for a in lista for x in a["_fluxos"]], data_ini, data_fim)
            if r is not None and base < BASE_MINIMA_CLASSE * max(v0, v1):
                r, aviso = None, "base_pequena"
        # Resultado = soma dos papéis que têm número (bate com a tabela por ativo); o
        # percentual exige todos — sem um papel, a base do Dietz da classe estaria errada.
        com_numero = [a["resultado"] for a in lista if a["resultado"] is not None]
        out.append({
            "classe": classe,
            "valor_ini": _r2(v0),
            "valor_fim": _r2(v1),
            "compras": _r2(sum(a["compras"] or 0.0 for a in lista)),
            "vendas": _r2(sum(a["vendas"] or 0.0 for a in lista)),
            "renda": _r2(sum(a["renda"] or 0.0 for a in lista)),
            "resultado": _r2(sum(com_numero)) if com_numero else None,
            "rentabilidade_pct": _pct(r),
            "status": status,
            "aviso": aviso,
        })
    return out


_GRAVIDADE = {"ok": 0, "estimado": 1, "sem_base": 2, "indisponivel": 3, "pendente": 4}


def _pior_status(status: Iterable[str]) -> str:
    return max(status, key=lambda s: _GRAVIDADE.get(s, 0), default="ok")


def transferencias_de_ativos(
    ref: Optional[str],
    payload: dict,
    payload_anterior: Optional[dict],
    data_ini: date,
    data_fim: date,
    regras: Sequence[Regra],
) -> list[tuple[str, float]]:
    """
    Ativos trazidos ou levados de outra corretora no mês (regra `ativo_mes` do dono), como
    (data, valor com sinal): entram como aporte/resgate também na rentabilidade do total.
    """
    if payload_anterior is None or not any(
        r.escopo == "ativo_mes" and r.data_referencia == ref and r.tipo in _TRANSFERENCIAS
        for r in regras
    ):
        return []
    return composicao_mes(ref, payload, payload_anterior, data_ini, data_fim, regras)["transferencias"]


# ---------------------------------------------------------------------------
# Janela: vários meses
# ---------------------------------------------------------------------------

def _status_janela(lista: Sequence[str]) -> str:
    """ok | estimado | parcial (algum mês sem número) | pendente | sem_base | indisponivel."""
    if "pendente" in lista:
        return "pendente"
    com_numero = [s for s in lista if s in STATUS_COM_NUMERO]
    if not com_numero:
        return "indisponivel" if "indisponivel" in lista else "sem_base"
    if len(com_numero) < len(lista):
        return "parcial"
    return "estimado" if "estimado" in com_numero else "ok"


def _novo(item: dict) -> dict:
    acc = {k: item.get(k) for k in ("chave", "ticker", "nome", "classe") if k in item}
    acc.update({
        "valor_ini": item["valor_ini"], "valor_fim": item["valor_fim"],
        "compras": 0.0, "vendas": 0.0, "renda": 0.0, "resultado": 0.0,
        "meses": 0, "meses_com_numero": 0, "_com_resultado": 0, "_fator": 1.0, "_status": [],
    })
    return acc


def _somar(acc: dict, item: dict) -> None:
    for k in ("ticker", "nome", "classe"):
        if item.get(k):
            acc[k] = item[k]
    acc["valor_fim"] = item["valor_fim"]
    if "quantidade_fim" in item:
        acc["quantidade_fim"] = item["quantidade_fim"]
    acc["meses"] += 1
    acc["_status"].append(item["status"])
    for k in ("compras", "vendas", "renda"):
        acc[k] += item[k] or 0.0
    if item["resultado"] is not None:
        acc["resultado"] += item["resultado"]
        acc["_com_resultado"] += 1
    if item["rentabilidade_pct"] is not None:
        acc["_fator"] *= 1 + item["rentabilidade_pct"] / 100
        acc["meses_com_numero"] += 1


def _fechar(acc: dict, presente: bool, total_fim: float) -> dict:
    fator = acc.pop("_fator")
    com_resultado = acc.pop("_com_resultado")
    acc["status"] = _status_janela(acc.pop("_status"))
    if not presente:            # saiu da carteira antes do fim da janela
        acc["valor_fim"] = 0.0
        if "quantidade_fim" in acc:
            acc["quantidade_fim"] = 0.0
    for k in ("compras", "vendas", "renda"):
        acc[k] = _r2(acc[k])
    acc["resultado"] = _r2(acc["resultado"]) if com_resultado else None
    acc["rentabilidade_pct"] = _pct(fator - 1) if acc["meses_com_numero"] else None
    acc["peso_fim_pct"] = round((acc["valor_fim"] or 0.0) / total_fim * 100, 2) if total_fim else None
    return acc


def acumular(composicoes: Sequence[dict]) -> dict:
    """
    Soma os meses de uma janela. Resultado em R$ somado; percentual encadeado só sobre os
    meses em que o papel (ou a classe) teve número. Valor e peso são os do último mês.
    """
    if not composicoes:
        return {"meses": [], "classes": [], "ativos": [], "caixa": None, "conciliacao": None,
                "avisos": [], "pendencias": [], "total_fim": None}

    papeis: dict[str, dict] = {}
    classes: dict[str, dict] = {}
    componentes = ("ganho_total", "ativos", "rendimento_caixa", "custos", "outros",
                   "renda_sem_papel", "transito", "residuo")
    conciliacao = {k: 0.0 for k in componentes}
    conferidos = 0
    caixa = {"rendimento": 0.0, "custos": 0.0}
    avisos: set[str] = set()
    pendencias: list[dict] = []

    for comp in composicoes:
        for a in comp["ativos"]:
            _somar(papeis.setdefault(a["chave"], _novo(a)), a)
            if a["pendencia"]:
                pendencias.append({
                    "mes": comp["mes"], "data_referencia": comp["data_referencia"],
                    **{k: a[k] for k in ("chave", "ticker", "nome", "classe", "quantidade_ini",
                                         "quantidade_fim", "preco_ini", "preco_fim", "pendencia")},
                })
        for c in comp["classes"]:
            _somar(classes.setdefault(c["classe"], _novo(c)), c)
        caixa["rendimento"] += comp["caixa"]["rendimento"] or 0.0
        caixa["custos"] += comp["caixa"]["custos"] or 0.0
        if comp["conciliacao"]["residuo"] is not None:
            conferidos += 1
            for k in componentes:
                conciliacao[k] += comp["conciliacao"][k] or 0.0
        avisos.update(comp["avisos"])

    ultimo = composicoes[-1]
    no_fim = {a["chave"] for a in ultimo["ativos"]}
    classes_no_fim = {c["classe"] for c in ultimo["classes"]}
    caixa_fim = ultimo["caixa"]["valor_fim"] or 0.0
    total_fim = sum(a["valor_fim"] or 0.0 for a in ultimo["ativos"]) + caixa_fim

    lista_classes = [_fechar(acc, acc["classe"] in classes_no_fim, total_fim) for acc in classes.values()]
    lista_ativos = [_fechar(acc, acc["chave"] in no_fim, total_fim) for acc in papeis.values()]
    return {
        "meses": [c["mes"] for c in composicoes],
        "classes": sorted(lista_classes, key=lambda c: -(c["valor_fim"] or 0.0)),
        "ativos": sorted(lista_ativos, key=lambda a: -abs(a["resultado"] or 0.0)),
        "caixa": {
            "valor_fim": _r2(caixa_fim),
            "peso_fim_pct": round(caixa_fim / total_fim * 100, 2) if total_fim else None,
            "rendimento": _r2(caixa["rendimento"]),
            "custos": _r2(caixa["custos"]),
        },
        "conciliacao": (
            {**{k: _r2(v) for k, v in conciliacao.items()}, "meses_conferidos": conferidos}
            if conferidos else None
        ),
        "avisos": sorted(avisos),
        "pendencias": pendencias,
        "total_fim": _r2(total_fim),
    }


def historico_do_papel(composicoes: Sequence[dict], chave: str) -> Optional[dict]:
    """Um papel mês a mês na janela, e o acumulado dele. None se ele não aparece."""
    linhas = []
    for comp in composicoes:
        papel = next((a for a in comp["ativos"] if a["chave"] == chave), None)
        if papel is not None:
            linhas.append({"mes": comp["mes"], "data_referencia": comp["data_referencia"], **papel})
    if not linhas:
        return None
    acc = _novo(linhas[0])
    for linha in linhas:
        _somar(acc, linha)
    ultimo = composicoes[-1]
    total_fim = sum(a["valor_fim"] or 0.0 for a in ultimo["ativos"]) + (ultimo["caixa"]["valor_fim"] or 0.0)
    presente = any(a["chave"] == chave for a in ultimo["ativos"])
    return {"meses": linhas, "acumulado": _fechar(acc, presente, total_fim)}


# ---------------------------------------------------------------------------
# Comparar dois fechamentos
# ---------------------------------------------------------------------------

def comparar(payload_de: dict, payload_ate: dict) -> dict:
    """
    O que entrou, saiu, mudou de quantidade ou só de preço entre dois extratos (por
    chave_externa), e a alocação por classe nas duas datas — com o caixa.
    """
    de, ate = _posicoes(payload_de), _posicoes(payload_ate)
    grupos: dict[str, list[dict]] = {"entraram": [], "sairam": [], "mudaram": [], "mantidos": []}
    for chave in sorted(set(de) | set(ate)):
        a, b = de.get(chave), ate.get(chave)
        base = b or a
        linha = {
            "chave": chave,
            "ticker": base.get("ticker"),
            "nome": base.get("nome"),
            "classe": base.get("classe"),
            "quantidade_de": _q(a) if a else None,
            "quantidade_ate": _q(b) if b else None,
            "valor_de": _r2(_v(a)) if a else None,
            "valor_ate": _r2(_v(b)) if b else None,
            "variacao": _r2(_v(b) - _v(a)),
        }
        if a is None:
            grupos["entraram"].append(linha)
        elif b is None:
            grupos["sairam"].append(linha)
        elif abs(_q(a) - _q(b)) > TOLERANCIA_QUANTIDADE:
            grupos["mudaram"].append(linha)
        else:
            grupos["mantidos"].append(linha)
    for lista in grupos.values():
        lista.sort(key=lambda x: -abs(x["variacao"] or 0.0))

    def _por_classe(payload: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in payload.get("posicoes") or []:
            classe = p.get("classe") or "OUTRO"
            out[classe] = out.get(classe, 0.0) + (_num(p.get("valor_mercado")) or 0.0)
        return out

    c_de, c_ate = _por_classe(payload_de), _por_classe(payload_ate)
    t_de, t_ate = sum(c_de.values()), sum(c_ate.values())
    classes = [
        {
            "classe": c,
            "valor_de": _r2(c_de.get(c, 0.0)),
            "valor_ate": _r2(c_ate.get(c, 0.0)),
            "peso_de": round(c_de.get(c, 0.0) / t_de * 100, 2) if t_de else None,
            "peso_ate": round(c_ate.get(c, 0.0) / t_ate * 100, 2) if t_ate else None,
        }
        for c in sorted(set(c_de) | set(c_ate))
    ]
    return {
        "posicoes": grupos,
        "classes": classes,
        "total_de": _r2(t_de),
        "total_ate": _r2(t_ate),
    }
