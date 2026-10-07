"""
Classificação dos lançamentos do razão da conta corrente (docs/PLANO_HISTORICO.md, Bloco 2).

Para a rentabilidade só uma pergunta importa: o dinheiro ENTROU OU SAIU da carteira (aporte,
resgate) ou só MUDOU DE LUGAR dentro dela (compra, venda, provento caindo na conta,
imposto)? Os tipos internos existem para a tela e para a composição por classe; para o total
da carteira, classificar errado ENTRE tipos internos não muda nada — só a fronteira
externo × interno muda o número.

A classificação acontece na hora do cálculo, nunca no import: o payload arquivado guarda só
a linha (seq, data, descrição sanitizada, valor com sinal, saldo). Assim uma regra criada
pelo dono hoje vale para todos os meses já arquivados, sem reprocessar nada.

Precedência:
  1. regra de linha (escopo 'linha') daquele mês e seq — só se a impressão da linha ainda
     confere (reimportar o mês com outro conteúdo invalida a regra daquela linha);
  2. regras de texto do dono: exato → prefixo (o mais longo primeiro) → contém (palavra
     inteira), respeitando o sinal quando a regra tem um;
  3. REGRAS_PADRAO, na mesma ordem;
  4. NAO_CLASSIFICADO.

Módulo puro: sem banco. As regras do dono vêm de app/tools/regras_lancamento.py.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .btg_xlsx_parser import _norm

# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

APORTE = "APORTE"
RESGATE = "RESGATE"
COMPRA_RV = "COMPRA_RV"
VENDA_RV = "VENDA_RV"
APLICACAO_RF = "APLICACAO_RF"
RESGATE_RF = "RESGATE_RF"
PROVENTO = "PROVENTO"
ALUGUEL = "ALUGUEL"
RENDIMENTO_CAIXA = "RENDIMENTO_CAIXA"
IMPOSTO = "IMPOSTO"
TAXA = "TAXA"
OUTRO_INTERNO = "OUTRO_INTERNO"
NAO_CLASSIFICADO = "NAO_CLASSIFICADO"

TIPOS_EXTERNOS = frozenset({APORTE, RESGATE})
TIPOS_INTERNOS = frozenset({
    COMPRA_RV, VENDA_RV, APLICACAO_RF, RESGATE_RF, PROVENTO, ALUGUEL, RENDIMENTO_CAIXA,
    IMPOSTO, TAXA, OUTRO_INTERNO,
})
TIPOS = TIPOS_EXTERNOS | TIPOS_INTERNOS | {NAO_CLASSIFICADO}

ROTULOS = {
    APORTE: "Aporte",
    RESGATE: "Resgate",
    COMPRA_RV: "Compra de ativo",
    VENDA_RV: "Venda de ativo",
    APLICACAO_RF: "Aplicação em renda fixa",
    RESGATE_RF: "Resgate de renda fixa",
    PROVENTO: "Provento",
    ALUGUEL: "Aluguel de ações",
    RENDIMENTO_CAIXA: "Rendimento do saldo",
    IMPOSTO: "Imposto",
    TAXA: "Taxa",
    OUTRO_INTERNO: "Outro (interno)",
    NAO_CLASSIFICADO: "Não classificado",
}

MODOS = ("exato", "prefixo", "contem")
SINAIS = ("credito", "debito")

# Escopo ativo_mes: o que o dono diz de uma quantidade que mudou sem negociação no mês.
EVENTO_SOCIETARIO = "EVENTO_SOCIETARIO"      # desdobramento, grupamento, bonificação
APORTE_EM_ATIVOS = "APORTE_EM_ATIVOS"        # ativo trazido de outra corretora
RESGATE_EM_ATIVOS = "RESGATE_EM_ATIVOS"      # ativo levado para outra corretora
TIPOS_ATIVO_MES = (EVENTO_SOCIETARIO, APORTE_EM_ATIVOS, RESGATE_EM_ATIVOS)

ROTULOS_ATIVO_MES = {
    EVENTO_SOCIETARIO: "Evento societário",
    APORTE_EM_ATIVOS: "Trazido de outra corretora",
    RESGATE_EM_ATIVOS: "Levado para outra corretora",
}


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Regra:
    tipo: str
    escopo: str = "texto"              # texto | linha | ativo_mes
    modo: str = "prefixo"              # exato | prefixo | contem (só escopo 'texto')
    padrao: str = ""                   # chave_de_texto(...) ou, em ativo_mes, a chave_externa
    sinal: Optional[str] = None        # credito | debito | None (vale para os dois)
    data_referencia: Optional[str] = None   # 'YYYY-MM-DD' — escopos linha e ativo_mes
    seq: Optional[int] = None
    impressao: Optional[str] = None
    id: Optional[int] = None           # None = regra padrão do sistema


def chave_de_texto(descricao: str) -> str:
    """Forma de casar: sem acento, minúscula, dígitos viram '#' (datas e valores variam)."""
    return re.sub(r"\d", "#", _norm(descricao))


def _padrao(tipo: str, padrao: str, modo: str = "prefixo", sinal: Optional[str] = None) -> Regra:
    return Regra(tipo=tipo, modo=modo, padrao=chave_de_texto(padrao), sinal=sinal)


# Conservadoras de propósito. Na dúvida, NAO_CLASSIFICADO: o dono decide na tela, uma vez,
# e a regra dele vale para os meses seguintes. Errar a fronteira externo/interno muda a
# rentabilidade; deixar pendente só a marca como provisória.
REGRAS_PADRAO: tuple[Regra, ...] = (
    # Renda que cai na conta (vista na fixture de 07/2026)
    _padrao(PROVENTO, "juros s/ capital"),
    _padrao(PROVENTO, "juros sobre capital"),
    _padrao(PROVENTO, "jcp"),
    _padrao(PROVENTO, "rendimento"),
    _padrao(PROVENTO, "dividendo"),
    _padrao(PROVENTO, "amortizacao"),
    _padrao(PROVENTO, "provento"),
    _padrao(PROVENTO, "cupom"),
    _padrao(PROVENTO, "cupom", modo="contem", sinal="credito"),
    # Crédito de juros na conta de investimento é renda (JCP, cupom de título). Débito de
    # juros seria custo — esse fica para o dono.
    _padrao(PROVENTO, "juros", sinal="credito"),
    _padrao(RENDIMENTO_CAIXA, "saldo final + rendimento"),
    _padrao(RENDIMENTO_CAIXA, "rendimento saldo"),
    _padrao(RENDIMENTO_CAIXA, "saldo remunerado", modo="contem"),
    _padrao(ALUGUEL, "aluguel"),
    _padrao(ALUGUEL, "aluguel", modo="contem"),
    # Custos
    _padrao(IMPOSTO, "irrf"),
    _padrao(IMPOSTO, "ir s/"),
    _padrao(IMPOSTO, "ir sobre"),
    _padrao(IMPOSTO, "iof"),
    _padrao(IMPOSTO, "imposto"),
    _padrao(IMPOSTO, "ir", modo="exato"),
    _padrao(TAXA, "taxa de custodia"),
    _padrao(TAXA, "custodia"),
    _padrao(TAXA, "corretagem"),
    _padrao(TAXA, "emolumentos"),
    _padrao(TAXA, "tarifa"),
    # Negociação: internas qualquer que seja o detalhe
    _padrao(COMPRA_RV, "liquidacao", sinal="debito"),
    _padrao(VENDA_RV, "liquidacao", sinal="credito"),
    _padrao(APLICACAO_RF, "compra tesouro"),
    _padrao(APLICACAO_RF, "aplicacao tesouro"),
    _padrao(RESGATE_RF, "venda tesouro"),
    _padrao(RESGATE_RF, "resgate tesouro"),
    _padrao(RESGATE_RF, "vencimento tesouro"),
    # Transferências: entrou ou saiu da carteira, pelo sinal. A descrição já chega
    # sanitizada pelo parser ('PIX RECEBIDO', 'TED ENVIADA', 'DEVOLUÇÃO TED').
    *(
        _padrao(tipo, marca, modo="contem", sinal=sinal)
        for marca in ("pix", "ted", "doc", "transf", "transferencia")
        for tipo, sinal in ((APORTE, "credito"), (RESGATE, "debito"))
    ),
    # ...menos transferência de custódia, que move ativos, não dinheiro: o valor que ela
    # carrega não é um aporte em caixa. Fica para o dono decidir.
    _padrao(NAO_CLASSIFICADO, "transf custodia"),
    _padrao(NAO_CLASSIFICADO, "transferencia de custodia"),
    _padrao(NAO_CLASSIFICADO, "transferencia custodia"),
)


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Classificacao:
    tipo: str
    origem: str                 # linha | regra | padrao | nenhuma
    regra_id: Optional[int] = None

    @property
    def externo(self) -> bool:
        return self.tipo in TIPOS_EXTERNOS


def impressao_linha(data_referencia: Optional[str], lancamento: dict) -> str:
    """Identidade do conteúdo da linha — a regra de linha só vale enquanto ela não muda."""
    base = f"{data_referencia}|{lancamento.get('data')}|{lancamento.get('descricao')}|{float(lancamento.get('valor') or 0):.2f}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def padrao_sugerido(descricao: str) -> str:
    """
    O começo genérico da descrição, para a tela oferecer "todas que começam com …":
    até 4 palavras, cortando no primeiro separador ou token com dígito.
    """
    tokens: list[str] = []
    for tok in _norm(descricao).split():
        if tok in {"-", "–", "—", "|", ":", "+"} or any(ch.isdigit() for ch in tok):
            break
        tokens.append(tok)
        if len(tokens) == 4:
            break
    return " ".join(tokens)


def _sinal(valor: float) -> Optional[str]:
    if valor > 0:
        return "credito"
    if valor < 0:
        return "debito"
    return None


def _casa(regra: Regra, chave: str, sinal: Optional[str]) -> bool:
    if regra.sinal and regra.sinal != sinal:
        return False
    if not regra.padrao:
        return False
    if regra.modo == "exato":
        return chave == regra.padrao
    if regra.modo == "prefixo":
        return chave.startswith(regra.padrao)
    if regra.modo == "contem":
        return re.search(rf"(?<!\w){re.escape(regra.padrao)}(?!\w)", chave) is not None
    return False


def _primeira(regras: Iterable[Regra], chave: str, sinal: Optional[str]) -> Optional[Regra]:
    """exato → prefixo (o mais longo primeiro) → contém (o mais longo primeiro)."""
    candidatas = [r for r in regras if r.escopo == "texto" and _casa(r, chave, sinal)]
    for modo in MODOS:
        do_modo = [r for r in candidatas if r.modo == modo]
        if do_modo:
            # Mais longo vence; empate → a regra com sinal (mais específica) vence.
            return max(do_modo, key=lambda r: (len(r.padrao), r.sinal is not None))
    return None


def classificar(
    lancamento: dict,
    regras_dono: Sequence[Regra] = (),
    data_referencia: Optional[str] = None,
) -> Classificacao:
    valor = float(lancamento.get("valor") or 0.0)
    sinal = _sinal(valor)

    if data_referencia is not None:
        impressao = None
        for r in regras_dono:
            if (r.escopo == "linha" and r.data_referencia == data_referencia
                    and r.seq == lancamento.get("seq")):
                impressao = impressao or impressao_linha(data_referencia, lancamento)
                if r.impressao == impressao:
                    return Classificacao(r.tipo, "linha", r.id)

    chave = chave_de_texto(lancamento.get("descricao") or "")
    regra = _primeira(regras_dono, chave, sinal)
    if regra is not None:
        return Classificacao(regra.tipo, "regra", regra.id)
    regra = _primeira(REGRAS_PADRAO, chave, sinal)
    if regra is not None:
        return Classificacao(regra.tipo, "padrao", None)
    return Classificacao(NAO_CLASSIFICADO, "nenhuma", None)


def classificar_mes(
    data_referencia: Optional[str],
    lancamentos: Sequence[dict],
    regras_dono: Sequence[Regra] = (),
) -> list[dict]:
    """Os lançamentos do mês com tipo, se é fluxo externo, de onde veio a classificação."""
    out: list[dict] = []
    for lanc in lancamentos:
        c = classificar(lanc, regras_dono, data_referencia)
        out.append({
            **lanc,
            "tipo": c.tipo,
            "externo": c.externo,
            "origem": c.origem,
            "regra_id": c.regra_id,
            "padrao_sugerido": padrao_sugerido(lanc.get("descricao") or ""),
        })
    return out


def fluxos_externos(classificados: Sequence[dict]) -> list[tuple[Optional[str], float]]:
    """
    (data, valor com sinal) dos aportes e resgates. O valor manda, não o rótulo: uma TED
    devolvida classificada como aporte entra com o sinal que tem no razão.
    """
    return [(c.get("data"), float(c["valor"])) for c in classificados if c.get("externo")]


# ---------------------------------------------------------------------------
# A que papel uma linha do razão se refere
# ---------------------------------------------------------------------------

_RE_TICKER = re.compile(r"\b([A-Z]{4}\d{1,2}[A-Z]?)\b")
_RE_ANO_FINAL = re.compile(r"\s*\d{4}\s*$")


def _nomes_do_titulo(chave: str, posicao: Optional[dict]) -> tuple[Optional[str], list[str]]:
    """Ano de vencimento e as formas de citar o título ('ntnb-p', 'ntnbp', 'tesouro ipca+')."""
    partes = chave.split(":")
    if len(partes) < 3:
        return None, []
    ano = partes[-1][:4] if partes[-1][:4].isdigit() else None
    sigla = _norm(partes[-2])
    nomes = {sigla, sigla.replace("-", " "), sigla.replace("-", "")}
    if posicao and posicao.get("nome"):
        nomes.add(_RE_ANO_FINAL.sub("", _norm(posicao["nome"])))
    return ano, [n for n in nomes if len(n) >= 3]


def ativo_ref(descricao: Optional[str], papeis: dict[str, Optional[dict]]) -> Optional[str]:
    """
    A chave_externa do papel que a descrição cita, entre `papeis` ({chave: posição}).
    Ação/FII pelo ticker; título pelo ano de vencimento mais a sigla ou o nome — o nome
    mais longo que casar decide ('Tesouro IPCA+ com Juros Semestrais' antes de 'Tesouro
    IPCA+'). Ambíguo ou sem menção → None: atribuir ao papel errado é pior que não atribuir.
    """
    if not descricao:
        return None
    for ticker in _RE_TICKER.findall(descricao.upper()):
        if f"B3:{ticker}" in papeis:
            return f"B3:{ticker}"
    n = _norm(descricao)
    melhores: list[tuple[int, str]] = []
    for chave, posicao in papeis.items():
        if not chave.startswith(("TD:", "RF:")):
            continue
        ano, nomes = _nomes_do_titulo(chave, posicao)
        if not ano or ano not in n:
            continue
        casados = [len(nome) for nome in nomes if nome in n]
        if casados:
            melhores.append((max(casados), chave))
    if not melhores:
        return None
    melhores.sort(reverse=True)
    if len(melhores) > 1 and melhores[0][0] == melhores[1][0]:
        return None
    return melhores[0][1]
