"""
Parser do extrato XLSX da conta de investimento do BTG Pactual.

Fonte única de verdade das posições (o caminho antigo — colagem do texto do PDF —
foi aposentado; ver docs/PLANO_XLSX.md).

Abas lidas: Capa (data de referência), Sumario (checksum), Renda Variavel, Renda Fixa,
Conta Corrente, Valores em Trânsito.

Princípios do parser (guardrails §1 do PLANO_XLSX):
  - Nada é localizado por índice fixo de linha/coluna: blocos são achados pelo título e
    as colunas são mapeadas pelo cabeçalho normalizado. O layout muda com o conteúdo do
    mês (um mês sem FII não tem o bloco de FIIs).
  - Linha de posição que não parseia NUNCA é silenciada: vai para `linhas_ignoradas`.
  - O total parseado é conferido contra a aba Sumario. Divergência vira aviso, não erro.
  - Sem data de referência não há import: `ExtratoParseError` (nunca inventar a data).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from io import BytesIO
from typing import Any, Optional

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

# Tolerância do checksum contra a aba Sumario. O próprio extrato arredonda: no extrato
# real de 07/2026 o Saldo Bruto de Renda Variável do Sumário (***) difere em R$ 0,11
# da soma das linhas de posição (***). Erro real de parser — uma posição perdida —
# é de ordem de grandeza muito maior (a menor posição da carteira é de centenas de reais),
# então R$ 1,00 separa ruído de erro com folga.
TOLERANCIA_CHECKSUM = 1.00

# Classes de Renda Variável, por título do bloco ("Posição > Ações" etc.)
_CLASSE_RV: dict[str, str] = {
    "acoes": "ACAO",
    "etf": "ETF",
    "fundos listados": "FII",
    "bdr": "BDR",
}

_TESOURO_NOME: dict[str, str] = {
    "LFT": "Tesouro Selic",
    "LTN": "Tesouro Prefixado",
    "NTNB-P": "Tesouro IPCA+",
    "NTNB": "Tesouro IPCA+ com Juros Semestrais",
    "NTN-B": "Tesouro IPCA+ com Juros Semestrais",
    "NTN-F": "Tesouro Prefixado com Juros Semestrais",
}

# Transações da aba de movimentação que são renda (e não compra/venda)
_PROVENTO_MARCAS = ("juros", "rendimento", "dividendo", "provento", "amortizacao")


class ExtratoParseError(Exception):
    """Erro estrutural no arquivo — a tool converte em tool_error para o usuário."""


# ---------------------------------------------------------------------------
# Conversores tolerantes
# ---------------------------------------------------------------------------

def _norm(v: Any) -> str:
    """Minúsculo, sem acento, com whitespace colapsado — para casar rótulos."""
    if v is None:
        return ""
    s = unicodedata.normalize("NFKD", str(v))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _txt(v: Any) -> str:
    """Texto exibível com whitespace colapsado ('BRASIL      ON  NM' → 'BRASIL ON NM')."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return _data(v) or ""
    return re.sub(r"\s+", " ", str(v)).strip()


def _num(v: Any) -> Optional[float]:
    """
    float | None. Aceita número nativo do openpyxl, '-' (nulo do BTG), vazio e string
    no formato brasileiro ('1.234,56') — o BTG pode voltar a exportar texto a qualquer
    release.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, (datetime, date)):
        return None
    s = str(v).strip().replace("R$", "").replace("%", "").strip()
    if not s or s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _data(v: Any) -> Optional[str]:
    """ISO YYYY-MM-DD. Aceita datetime/date do openpyxl e texto dd/mm/aa(aa)."""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if v is None:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{2,4})", str(v))
    if not m:
        return None
    d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def _ano(iso: Optional[str]) -> str:
    return iso[:4] if iso else "?"


def _slug(texto: str) -> str:
    """Fragmento de chave a partir de texto livre: sem acento, sem pontuação, maiúsculo."""
    return re.sub(r"[^a-z0-9]+", "-", _norm(texto)).strip("-").upper()


# ---------------------------------------------------------------------------
# Modelos de saída
# ---------------------------------------------------------------------------

@dataclass
class PosicaoParsed:
    ticker: Optional[str]
    nome: str
    classe: str                       # ACAO | ETF | FII | BDR | TESOURO | RF | CAIXA
    quantidade: float
    preco_medio: Optional[float]      # custo médio de aquisição (nunca o preço atual)
    valor_mercado: float              # saldo bruto na data do extrato
    preco_fechamento: Optional[float]
    as_of: Optional[str]              # YYYY-MM-DD
    vencimento: Optional[str] = None  # renda fixa
    taxa_contratada: Optional[str] = None
    custo_total: Optional[float] = None
    # Identidade do papel entre extratos — ver a seção "Identidade do papel entre
    # extratos". O `nome` não serve: o BTG o reescreve de um mês para o outro
    # ('FII HGCR PAXCI' → 'FII HGCR PAXCI ER').
    chave_externa: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtratoParsed:
    posicoes: list[PosicaoParsed] = field(default_factory=list)
    data_referencia: Optional[str] = None
    sumario: dict = field(default_factory=dict)
    proventos: list[dict] = field(default_factory=list)
    movimentacoes: list[dict] = field(default_factory=list)
    aluguel: list[dict] = field(default_factory=list)
    valores_em_transito: list[dict] = field(default_factory=list)
    linhas_ignoradas: list[str] = field(default_factory=list)
    checagem: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posicoes"] = [p.to_dict() for p in self.posicoes]
        return d


# ---------------------------------------------------------------------------
# Identidade do papel entre extratos
# ---------------------------------------------------------------------------
#
# O `nome` do extrato não é identidade: o BTG o reescreve de um mês para o outro
# ('ITAUUNIBANCOPN N1' → 'ITAUUNIBANCOPN EJ N1' quando o papel vai ex-juros). Casar
# posição por nome faz o upsert criar uma linha nova e abandonar a antiga — o ativo
# "renasce" e perde histórico. A chave abaixo é construída do que não muda:
#
#   RV       B3:BBAS3                          ticker da B3
#   TESOURO  TD:LFT:2031-03-01                 sigla do título + vencimento
#   RF       RF:BANCO-XP:CDB:2027-06-15        emissor + sigla + vencimento
#   CAIXA    CAIXA:BTG                         conta corrente da corretora
#
# Renda fixa privada leva o emissor porque dois CDBs de bancos diferentes podem ter
# a mesma sigla e o mesmo vencimento — são papéis distintos, com risco de crédito
# distinto, e não podem colidir numa posição só.

_SEM_VENCIMENTO = "sem-vencimento"


def _chave_rv(ticker: str) -> str:
    return f"B3:{ticker.upper()}"


def _chave_titulo(eh_tesouro: bool, emissor: str, sigla: str, vencimento: Optional[str]) -> str:
    venc = vencimento or _SEM_VENCIMENTO
    if eh_tesouro:
        return f"TD:{_slug(sigla)}:{venc}"
    return f"RF:{_slug(emissor)}:{_slug(sigla)}:{venc}"


# ---------------------------------------------------------------------------
# Varredura genérica: títulos, cabeçalhos e tabelas
# ---------------------------------------------------------------------------

@dataclass
class _Tabela:
    titulo: str
    header: list[str]         # normalizado
    header_raw: list[str]
    linhas: list[list[Any]] = field(default_factory=list)
    totais: list[list[Any]] = field(default_factory=list)


def _preenchidas(row: list[Any]) -> list[Any]:
    return [c for c in row if c is not None and str(c).strip() != ""]


def _eh_titulo(row: list[Any]) -> bool:
    """'Renda Variável', 'Posição', 'Posição > Ações', 'Posição > Ações | Aluguel'."""
    vals = _preenchidas(row)
    if not vals:
        return False
    if any(isinstance(c, (int, float, datetime, date)) and not isinstance(c, bool) for c in vals):
        return False
    if len(vals) == 1:
        return True
    return ">" in _txt(vals[0])


def _eh_total(row: list[Any]) -> bool:
    vals = _preenchidas(row)
    return bool(vals) and _norm(vals[0]).startswith("total")


def _eh_header(row: list[Any]) -> bool:
    """Linha só de rótulos textuais, com 2+ colunas, que não é título nem total."""
    if _eh_titulo(row) or _eh_total(row):
        return False
    vals = _preenchidas(row)
    if len(vals) < 2:
        return False
    if any(isinstance(c, (int, float, datetime, date)) and not isinstance(c, bool) for c in vals):
        return False
    return all(_num(c) is None for c in vals)


def _tabelas(ws) -> list[_Tabela]:
    """Quebra a planilha em tabelas (título + cabeçalho + linhas + linhas de total)."""
    tabelas: list[_Tabela] = []
    titulo = ""
    atual: Optional[_Tabela] = None

    for raw in ws.iter_rows(values_only=True):
        row = list(raw)
        if not _preenchidas(row):
            atual = None
            continue
        if _eh_titulo(row):
            titulo = " | ".join(_txt(c) for c in _preenchidas(row))
            atual = None
            continue
        if _eh_header(row):
            atual = _Tabela(
                titulo=titulo,
                header=[_norm(c) for c in row],
                header_raw=[_txt(c) for c in row],
            )
            tabelas.append(atual)
            continue
        if atual is None:
            continue
        if _eh_total(row):
            atual.totais.append(row)
        else:
            atual.linhas.append(row)

    return tabelas


def _idx(tab: _Tabela, *alvos: str) -> Optional[int]:
    """Índice da coluna pelo rótulo: casamento exato primeiro, depois por prefixo."""
    normalizados = [_norm(a) for a in alvos]
    for alvo in normalizados:
        for i, h in enumerate(tab.header):
            if h == alvo:
                return i
    for alvo in normalizados:
        for i, h in enumerate(tab.header):
            if h and (h.startswith(alvo) or alvo in h):
                return i
    return None


def _cel(row: list[Any], i: Optional[int]) -> Any:
    if i is None or i >= len(row):
        return None
    return row[i]


def _aba(wb, nome: str):
    """Aba pelo nome normalizado — o título tem acento ('Valores em Trânsito')."""
    alvo = _norm(nome)
    for ws in wb.worksheets:
        if _norm(ws.title) == alvo:
            return ws
    for ws in wb.worksheets:
        if alvo in _norm(ws.title):
            return ws
    return None


def _resumo_linha(titulo: str, row: list[Any]) -> str:
    conteudo = " | ".join(_txt(c) for c in _preenchidas(row))
    return f"[{titulo}] {conteudo}"[:300]


# ---------------------------------------------------------------------------
# Capa — data de referência
# ---------------------------------------------------------------------------

def _parse_capa(wb) -> tuple[Optional[str], dict]:
    ws = _aba(wb, "Capa")
    if ws is None:
        raise ExtratoParseError("Aba 'Capa' não encontrada — o arquivo não parece um extrato do BTG.")

    data_ref: Optional[str] = None
    emitido_em: Optional[str] = None
    periodo_inicio: Optional[str] = None

    for row in ws.iter_rows(values_only=True):
        for cell in row:
            texto = _txt(cell)
            if not texto:
                continue
            n = _norm(texto)
            if n.startswith("periodo de"):
                datas = re.findall(r"\d{2}/\d{2}/\d{2,4}", texto)
                if len(datas) >= 2:
                    periodo_inicio, data_ref = _data(datas[0]), _data(datas[1])
                elif datas:
                    data_ref = _data(datas[0])
            elif n.startswith("emitido em"):
                emitido_em = _data(texto)

    if not data_ref:
        raise ExtratoParseError(
            "Não encontrei o período do extrato na aba 'Capa' "
            "(linha 'Período de DD/MM/AA a DD/MM/AA'). Sem data de referência não importo."
        )
    return data_ref, {"periodo_inicio": periodo_inicio, "emitido_em": emitido_em}


# ---------------------------------------------------------------------------
# Sumario — totais do mês atual e do anterior (base do checksum)
# ---------------------------------------------------------------------------

def _parse_sumario(wb) -> dict:
    ws = _aba(wb, "Sumario")
    if ws is None:
        return {}

    tab = next((t for t in _tabelas(ws) if _idx(t, "mercados") is not None), None)
    if tab is None:
        return {}

    i_mercado = _idx(tab, "mercados")

    # Rótulos são 'Saldo Bruto R$ 30/06/26' — as datas mudam todo mês, então a coluna é
    # identificada por bruto/líquido + data extraída do próprio rótulo.
    colunas: list[tuple[int, str, Optional[str]]] = []
    for i, raw in enumerate(tab.header_raw):
        n = _norm(raw)
        if not n.startswith("saldo"):
            continue
        tipo = "bruto" if "bruto" in n else "liquido"
        colunas.append((i, tipo, _data(raw)))

    if not colunas:
        return {}

    datas = sorted({d for _, _, d in colunas if d})
    data_atual = datas[-1] if datas else None
    data_anterior = datas[0] if len(datas) > 1 else None

    def _periodo(data_alvo: Optional[str]) -> dict:
        alvo = [(i, tipo) for i, tipo, d in colunas if d == data_alvo]
        if not alvo and data_alvo is None:
            alvo = [(i, tipo) for i, tipo, _ in colunas]
        mercados: dict[str, dict] = {}
        for row in tab.linhas:
            nome = _txt(_cel(row, i_mercado))
            if not nome:
                continue
            mercados[nome] = {tipo: _num(_cel(row, i)) for i, tipo in alvo}
        totais: dict[str, Optional[float]] = {}
        if tab.totais:
            totais = {tipo: _num(_cel(tab.totais[0], i)) for i, tipo in alvo}
        return {"data": data_alvo, "mercados": mercados, "total": totais}

    sumario = {"atual": _periodo(data_atual)}
    if data_anterior:
        sumario["anterior"] = _periodo(data_anterior)
    return sumario


def _sumario_mercado(sumario: dict, chave: str) -> Optional[float]:
    atual = sumario.get("atual") or {}
    for nome, valores in (atual.get("mercados") or {}).items():
        if _norm(nome) == _norm(chave):
            return valores.get("bruto")
    return None


# ---------------------------------------------------------------------------
# Renda Variável
# ---------------------------------------------------------------------------

def _parse_renda_variavel(wb, as_of: str, ignoradas: list[str]) -> tuple[list[PosicaoParsed], list[dict], list[dict], list[dict]]:
    ws = _aba(wb, "Renda Variavel")
    posicoes: list[PosicaoParsed] = []
    proventos: list[dict] = []
    movimentacoes: list[dict] = []
    aluguel: list[dict] = []
    if ws is None:
        return posicoes, proventos, movimentacoes, aluguel

    for tab in _tabelas(ws):
        t = _norm(tab.titulo)
        eh_aluguel = "aluguel" in t

        if t.startswith("posicao >") and eh_aluguel:
            aluguel.extend(_parse_aluguel(tab))
        elif t.startswith("posicao >"):
            classe = _classe_rv(t)
            if classe is None:
                ignoradas.append(f"[{tab.titulo}] bloco de posição não reconhecido — {len(tab.linhas)} linha(s)")
                continue
            posicoes.extend(_parse_rv(tab, classe, as_of, ignoradas))
        elif t.startswith("movimentacao >") and not eh_aluguel:
            p, m = _parse_movimentacao(tab)
            proventos.extend(p)
            movimentacoes.extend(m)
        # 'Movimentação > Ações | Aluguel' é redundante com a posição de aluguel: ignorado.

    return posicoes, proventos, movimentacoes, aluguel


def _classe_rv(titulo_norm: str) -> Optional[str]:
    depois = titulo_norm.split(">", 1)[1].strip() if ">" in titulo_norm else titulo_norm
    for marca, classe in _CLASSE_RV.items():
        if marca in depois:
            return classe
    return None


def _parse_rv(tab: _Tabela, classe: str, as_of: str, ignoradas: list[str]) -> list[PosicaoParsed]:
    i_cod = _idx(tab, "codigo")
    i_nome = _idx(tab, "acao", "ativo")
    i_qtde = _idx(tab, "qtde", "quantidade")
    i_fech = _idx(tab, "preco fechamento")
    i_medio = _idx(tab, "preco medio")
    i_saldo = _idx(tab, "saldo bruto")

    out: list[PosicaoParsed] = []
    for row in tab.linhas:
        ticker = _txt(_cel(row, i_cod)).upper()
        saldo = _num(_cel(row, i_saldo))
        qtde = _num(_cel(row, i_qtde))
        if not ticker or saldo is None:
            ignoradas.append(_resumo_linha(tab.titulo, row))
            continue
        out.append(PosicaoParsed(
            ticker=ticker,
            nome=_txt(_cel(row, i_nome)) or ticker,
            classe=classe,
            quantidade=qtde if qtde is not None else 0.0,
            preco_medio=_num(_cel(row, i_medio)),
            valor_mercado=saldo,
            preco_fechamento=_num(_cel(row, i_fech)),
            as_of=as_of,
            chave_externa=_chave_rv(ticker),
        ))
    return out


def _parse_aluguel(tab: _Tabela) -> list[dict]:
    """
    Ações doadas em aluguel. NÃO é posição: o papel já está contado na posição de Ações
    (TAEE11 aparece nos dois blocos). Somar duplicaria o ativo.
    """
    i_cod = _idx(tab, "codigo")
    i_qtde = _idx(tab, "qtde", "quantidade")
    i_pos = _idx(tab, "posicao")
    i_valor = _idx(tab, "valor contratado")
    i_venc = _idx(tab, "data vencimento")
    i_taxa = _idx(tab, "taxa ano", "taxa")
    i_result = _idx(tab, "result")

    out: list[dict] = []
    for row in tab.linhas:
        cod = _txt(_cel(row, i_cod)).upper()
        if not cod:
            continue
        out.append({
            "ticker": cod,
            "quantidade": _num(_cel(row, i_qtde)),
            "posicao": _txt(_cel(row, i_pos)),
            "valor_contratado": _num(_cel(row, i_valor)),
            "vencimento": _data(_cel(row, i_venc)),
            "taxa_ano_pct": _num(_cel(row, i_taxa)),
            "resultado_acumulado_liquido": _num(_cel(row, i_result)),
        })
    return out


def _parse_movimentacao(tab: _Tabela) -> tuple[list[dict], list[dict]]:
    i_data = _idx(tab, "data")
    i_trans = _idx(tab, "transacao")
    i_cod = _idx(tab, "codigo")
    i_qtde = _idx(tab, "qtde", "quantidade")
    i_bruto = _idx(tab, "valor bruto")
    i_liq = _idx(tab, "valor liquido")

    proventos: list[dict] = []
    outras: list[dict] = []
    for row in tab.linhas:
        transacao = _txt(_cel(row, i_trans))
        if not transacao:
            continue
        item = {
            "data": _data(_cel(row, i_data)),
            "transacao": transacao,
            "ticker": _txt(_cel(row, i_cod)).upper() or None,
            "quantidade": _num(_cel(row, i_qtde)),
            "valor_bruto": _num(_cel(row, i_bruto)),
            "valor_liquido": _num(_cel(row, i_liq)),
        }
        n = _norm(transacao)
        (proventos if any(m in n for m in _PROVENTO_MARCAS) else outras).append(item)
    return proventos, outras


# ---------------------------------------------------------------------------
# Renda Fixa (Tesouro Direto e, se houver, RF privada)
# ---------------------------------------------------------------------------

def _chave_rf(sigla: str, vencimento: Optional[str]) -> tuple[str, str]:
    """Chave de casamento posição ↔ lote de aquisição, dentro de um mesmo extrato."""
    return (sigla.upper(), vencimento or "")


def _parse_renda_fixa(wb, as_of: str, ignoradas: list[str]) -> list[PosicaoParsed]:
    ws = _aba(wb, "Renda Fixa")
    if ws is None:
        return []

    # Posições são agregadas pela identidade do papel (chave_externa); os lotes de
    # aquisição casam por (sigla, vencimento), que é o que o Detalhamento traz.
    posicoes: dict[str, PosicaoParsed] = {}
    chaves_lote: dict[str, tuple[tuple[str, str], str]] = {}
    lotes: dict[tuple[str, str], dict[str, dict]] = {}

    for tab in _tabelas(ws):
        t = _norm(tab.titulo)
        if t.startswith("posicao consolidada"):
            continue  # conferência por emissor — nada a extrair
        if t.startswith("posicao >"):
            _acumula_posicao_rf(tab, as_of, posicoes, chaves_lote, ignoradas)
        elif t.startswith("detalhamento >"):
            _acumula_lotes_rf(tab, lotes)

    # Custo real de aquisição: só existe no Detalhamento. Sem lote casado, preco_medio
    # fica None — nunca o preço atual disfarçado de custo (era o erro do parser de PDF).
    disputados = Counter(cl for cl, _ in chaves_lote.values())
    for chave, pos in posicoes.items():
        chave_lote, emissor_slug = chaves_lote[chave]
        lote = _lote_do_papel(
            lotes.get(chave_lote), emissor_slug, disputado=disputados[chave_lote] > 1
        )
        if lote and lote["quantidade"]:
            # Média ponderada pelo preço de compra declarado; o valor de compra (já
            # arredondado em centavos pelo BTG) é o fallback.
            base = lote["preco_ponderado"] or lote["valor_compra"]
            pos.preco_medio = round(base / lote["quantidade"], 2)
            pos.custo_total = round(lote["valor_compra"], 2)
        else:
            logger.info("renda fixa: sem lote de aquisição para %s — preco_medio ficará nulo", chave)

    return list(posicoes.values())


def _lote_do_papel(
    por_emissor: Optional[dict[str, dict]], emissor_slug: str, disputado: bool
) -> Optional[dict]:
    """
    Escolhe o lote de aquisição do papel. O Detalhamento não traz coluna de emissor —
    ele vem no título do bloco —, então com um único bloco e um único papel disputando
    a chave o casamento é direto.

    `disputado` = mais de um papel (emissores diferentes, mesma sigla e vencimento)
    aponta para esta chave de lote. Aí só o emissor exato serve: aplicar o lote errado
    inventaria um custo médio, e custo inventado é pior que custo ausente.
    """
    if not por_emissor:
        return None
    if len(por_emissor) == 1 and not disputado:
        return next(iter(por_emissor.values()))
    return por_emissor.get(emissor_slug)


def _acumula_posicao_rf(
    tab: _Tabela,
    as_of: str,
    posicoes: dict[str, PosicaoParsed],
    chaves_lote: dict[str, tuple[tuple[str, str], str]],
    ignoradas: list[str],
) -> None:
    i_emissor = _idx(tab, "emissor")
    i_ativo = _idx(tab, "ativo")
    i_venc = _idx(tab, "vencimento")
    i_taxa = _idx(tab, "taxa media ponderada", "taxa")
    i_qtde = _idx(tab, "quantidade", "qtde")
    i_preco = _idx(tab, "preco r$", "preco")
    i_saldo = _idx(tab, "saldo bruto")

    # 'Posição > TESOURO DIRETO - LFT' — usado quando a linha não traz a coluna Ativo
    sigla_titulo = tab.titulo.split("-")[-1].strip().upper() if "-" in tab.titulo else ""
    eh_tesouro_titulo = "tesouro direto" in _norm(tab.titulo)

    for row in tab.linhas:
        saldo = _num(_cel(row, i_saldo))
        sigla = (_txt(_cel(row, i_ativo)) or sigla_titulo).upper()
        vencimento = _data(_cel(row, i_venc))
        if saldo is None or not sigla:
            ignoradas.append(_resumo_linha(tab.titulo, row))
            continue

        emissor = _txt(_cel(row, i_emissor))
        eh_tesouro = eh_tesouro_titulo or "BACEN" in emissor.upper()
        ano = _ano(vencimento)
        qtde = _num(_cel(row, i_qtde)) or 0.0
        preco = _num(_cel(row, i_preco))
        taxa = _txt(_cel(row, i_taxa)) or None

        emissor_curto = emissor.split(" - ")[0].strip()[:40]
        if eh_tesouro:
            nome = f"{_TESOURO_NOME.get(sigla, sigla)} {ano}"
            ticker: Optional[str] = nome
            classe = "TESOURO"
        else:
            nome = f"{sigla} {emissor_curto or 'emissor não identificado'} {ano}".strip()
            ticker = None
            classe = "RF"

        chave = _chave_titulo(eh_tesouro, emissor_curto, sigla, vencimento)
        existente = posicoes.get(chave)
        if existente:
            # Mesmo papel em duas linhas (emissões diferentes do mesmo título): agrega.
            existente.quantidade += qtde
            existente.valor_mercado += saldo
        else:
            chaves_lote[chave] = (_chave_rf(sigla, vencimento), _slug(emissor_curto))
            posicoes[chave] = PosicaoParsed(
                ticker=ticker,
                nome=nome,
                classe=classe,
                quantidade=qtde,
                preco_medio=None,
                valor_mercado=saldo,
                preco_fechamento=preco,
                as_of=as_of,
                vencimento=vencimento,
                taxa_contratada=taxa,
                chave_externa=chave,
            )


def _acumula_lotes_rf(tab: _Tabela, lotes: dict[tuple[str, str], dict[str, dict]]) -> None:
    i_ativo = _idx(tab, "ativo")
    i_venc = _idx(tab, "vencimento")
    i_qtde = _idx(tab, "quantidade", "qtde")
    i_valor = _idx(tab, "valor compra")
    i_preco = _idx(tab, "preco compra")

    # 'Detalhamento > TESOURO DIRETO - LFT | BACEN-BANCO CENTRAL DO BRASIL - RJ':
    # a sigla vem antes do '|', o emissor depois — as linhas não repetem o emissor.
    cabecalho, _, emissor_titulo = tab.titulo.partition("|")
    sigla_titulo = cabecalho.split("-")[-1].strip().upper() if "-" in cabecalho else ""
    emissor_slug = _slug(emissor_titulo.split(" - ")[0].strip()[:40])

    for row in tab.linhas:
        sigla = (_txt(_cel(row, i_ativo)) or sigla_titulo).upper()
        qtde = _num(_cel(row, i_qtde))
        valor = _num(_cel(row, i_valor))
        if not sigla or qtde is None or valor is None:
            continue
        preco = _num(_cel(row, i_preco))
        chave = _chave_rf(sigla, _data(_cel(row, i_venc)))
        acc = lotes.setdefault(chave, {}).setdefault(
            emissor_slug, {"quantidade": 0.0, "valor_compra": 0.0, "preco_ponderado": 0.0, "lotes": 0}
        )
        acc["quantidade"] += qtde
        acc["valor_compra"] += valor
        acc["preco_ponderado"] += qtde * preco if preco is not None else valor
        acc["lotes"] += 1


# ---------------------------------------------------------------------------
# Conta Corrente (CAIXA) e Valores em Trânsito
# ---------------------------------------------------------------------------

def _parse_conta_corrente(wb, as_of: str) -> Optional[PosicaoParsed]:
    ws = _aba(wb, "Conta Corrente")
    if ws is None:
        return None

    for tab in _tabelas(ws):
        i_valor = _idx(tab, "valor financeiro")
        if i_valor is None:
            continue
        i_data = _idx(tab, "data")
        for row in reversed(tab.linhas):   # último saldo do período
            valor = _num(_cel(row, i_valor))
            if valor is None:
                continue
            return PosicaoParsed(
                ticker=None,
                nome="Conta corrente BTG",
                classe="CAIXA",
                quantidade=1.0,
                preco_medio=None,
                valor_mercado=valor,
                preco_fechamento=None,
                as_of=_data(_cel(row, i_data)) or as_of,
                chave_externa="CAIXA:BTG",
            )
    return None


def _parse_valores_transito(wb) -> list[dict]:
    ws = _aba(wb, "Valores em Trânsito")
    if ws is None:
        return []

    out: list[dict] = []
    for tab in _tabelas(ws):
        i_data = _idx(tab, "data liquidacao", "data")
        i_desc = _idx(tab, "descricao")
        i_valor = _idx(tab, "valor r$", "valor")
        if i_valor is None:
            continue
        for row in tab.linhas:
            valor = _num(_cel(row, i_valor))
            if valor is None:
                continue
            out.append({
                "data_liquidacao": _data(_cel(row, i_data)),
                "descricao": _txt(_cel(row, i_desc)),
                "valor": valor,
                "origem": tab.titulo,
            })
    return out


# ---------------------------------------------------------------------------
# Checksum contra a aba Sumario
# ---------------------------------------------------------------------------

_CLASSES_RV = {"ACAO", "ETF", "FII", "BDR"}
_CLASSES_RF = {"TESOURO", "RF"}


def _checagem(posicoes: list[PosicaoParsed], sumario: dict, transito: float) -> dict:
    def _soma(classes: set[str]) -> float:
        return round(sum(p.valor_mercado for p in posicoes if p.classe in classes), 2)

    parseado = {
        "Renda Variável": _soma(_CLASSES_RV),
        "Renda Fixa": _soma(_CLASSES_RF),
        "Conta Corrente": _soma({"CAIXA"}),
    }

    comparacoes: list[dict] = []
    for mercado, valor in parseado.items():
        esperado = _sumario_mercado(sumario, mercado)
        if esperado is None:
            continue
        comparacoes.append({
            "mercado": mercado,
            "parseado": valor,
            "sumario": round(esperado, 2),
            "diferenca": round(valor - esperado, 2),
        })

    total_parseado = round(sum(p.valor_mercado for p in posicoes), 2)
    total_sumario = ((sumario.get("atual") or {}).get("total") or {}).get("bruto")
    # O total do Sumário inclui Valores em Trânsito, que não são posição.
    esperado_total = round(total_sumario - transito, 2) if total_sumario is not None else None
    diferenca_total = round(total_parseado - esperado_total, 2) if esperado_total is not None else None

    ok = (
        diferenca_total is not None
        and abs(diferenca_total) <= TOLERANCIA_CHECKSUM
        and all(abs(c["diferenca"]) <= TOLERANCIA_CHECKSUM for c in comparacoes)
    )

    resultado = {
        "ok": ok,
        "total_parseado": total_parseado,
        "total_esperado": esperado_total,
        "diferenca": diferenca_total,
        "por_mercado": comparacoes,
        "valores_em_transito_excluidos": round(transito, 2),
        "tolerancia": TOLERANCIA_CHECKSUM,
    }
    if esperado_total is None:
        resultado["aviso"] = "Aba 'Sumario' sem total — não foi possível conferir o import."
    elif not ok:
        resultado["aviso"] = (
            f"O total das posições lidas (R$ {total_parseado:,.2f}) não bate com o "
            f"Sumário do extrato (R$ {esperado_total:,.2f}). Confira antes de gravar."
        )
    return resultado


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

def parse_btg_xlsx(conteudo: bytes) -> ExtratoParsed:
    """
    Parseia o extrato XLSX do BTG. Levanta ExtratoParseError se o arquivo não for
    legível ou não tiver data de referência.
    """
    try:
        wb = load_workbook(BytesIO(conteudo), data_only=True)
    except Exception as e:
        raise ExtratoParseError(f"Não consegui abrir o arquivo como XLSX: {e}") from e

    try:
        data_ref, meta = _parse_capa(wb)
        ignoradas: list[str] = []

        sumario = _parse_sumario(wb)
        pos_rv, proventos, movimentacoes, aluguel = _parse_renda_variavel(wb, data_ref, ignoradas)
        pos_rf = _parse_renda_fixa(wb, data_ref, ignoradas)
        caixa = _parse_conta_corrente(wb, data_ref)
        transito = _parse_valores_transito(wb)
    finally:
        wb.close()

    posicoes = pos_rv + pos_rf + ([caixa] if caixa else [])
    if not posicoes:
        raise ExtratoParseError(
            "Nenhuma posição encontrada no arquivo. Confira se o XLSX é o extrato da "
            "conta de investimento do BTG (abas 'Renda Variavel' / 'Renda Fixa')."
        )

    total_transito = sum(v["valor"] for v in transito)
    extrato = ExtratoParsed(
        posicoes=posicoes,
        data_referencia=data_ref,
        sumario=sumario,
        proventos=proventos,
        movimentacoes=movimentacoes,
        aluguel=aluguel,
        valores_em_transito=transito,
        linhas_ignoradas=ignoradas,
        checagem=_checagem(posicoes, sumario, total_transito),
    )
    extrato.sumario = {**sumario, "meta": meta} if sumario else {"meta": meta}

    logger.info(
        "parse_btg_xlsx: %d posicoes, ref=%s, checksum_ok=%s, %d linha(s) ignorada(s)",
        len(posicoes), data_ref, extrato.checagem.get("ok"), len(ignoradas),
    )
    return extrato
