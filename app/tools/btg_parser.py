"""
Parser do extrato PDF do BTG Pactual (colagem de texto).

Seções suportadas: Ações, ETF, Fundos Listados (FIIs), Tesouro Direto (LFT, LTN, NTNB-P).
RF privada (CDB/LCI/LCA) não aparece como tabela estruturada no PDF — deve ser lançada
manualmente via POST /posicoes.

Validado com extrato real (05/2026): 14/14 posições corretas, total R$ 44.363,04.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class PosicaoParsed:
    ticker: str
    nome: str
    classe: str           # ACAO | ETF | FII | TESOURO
    quantidade: float
    preco_medio: Optional[float]     # preço médio de aquisição (RV) / preço unitário (Tesouro)
    valor_mercado: float             # saldo bruto na data do extrato
    preco_fechamento: Optional[float]
    as_of: Optional[str]             # YYYY-MM-DD

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _br(s: str) -> float:
    """Converte número brasileiro para float: '19.100,18' → 19100.18"""
    return float(s.strip().replace(".", "").replace(",", "."))


# ---------------------------------------------------------------------------
# Marcadores de seção
# ---------------------------------------------------------------------------

_SECTION_STARTS: dict[str, str] = {
    "Renda variável - Posição - Ações":           "acoes",
    "Renda variável - Posição - ETF":             "etf",
    "Renda variável - Posição - Fundos Listados": "fiis",
    "Renda fixa - Posição - TESOURO DIRETO":      "tesouro",
}

_SECTION_EXITS: list[str] = [
    "Renda variável - Movimentação",
    "Renda fixa - Detalhamento",
    "Renda fixa - Movimentação",
    "Renda fixa - Posição Consolidada",
    "Conta corrente",
    "Valores em trânsito",
    "Distribuição Setorial",
]

_NOISE_PREFIXES: tuple[str, ...] = (
    "Emissor", "Código", "SAC:", "Extrato da", "Período de",
    "Emitido em", "índice", "Leitura", "Total", "RENDA", "Sumário",
    "Mercados", "Renda Variável", "Renda Fixa", "Conta Corrente",
    "VALORES EM", "Perfil de Risco", "Disclaimers", "Geral",
    "Suitability", "Fale Conosco", "Distribui",
)


def _is_noise(line: str) -> bool:
    if not line:
        return True
    if line.startswith(_NOISE_PREFIXES):
        return True
    if re.match(r"^[\d.,\s\-]+$", line):   # subtotais numéricos
        return True
    if "BACEN" in line or "BRASIL - RJ" in line:
        return True
    return False


# ---------------------------------------------------------------------------
# Parsers por tipo de linha
# ---------------------------------------------------------------------------

def _parse_rv(line: str, classe: str, as_of: Optional[str]) -> Optional[PosicaoParsed]:
    """
    Ações / ETF:  TICKER NOME QTDE PRECO_FECH PRECO_MEDIO SALDO_BRUTO
    Ex.: BBAS3 BRASIL ON NM 100 20,30 25,23 2.030,00
         ITUB4 ITAUUNIBANCOPN N1 47 40,04 42,01 1.881,88
    """
    m = re.match(
        r"^([A-Z]{4,6}\d{0,2})\s+(.+?)\s+(\d+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$",
        line,
    )
    if not m:
        return None
    return PosicaoParsed(
        ticker=m.group(1),
        nome=m.group(2).strip(),
        classe=classe,
        quantidade=float(m.group(3)),
        preco_fechamento=_br(m.group(4)),
        preco_medio=_br(m.group(5)),
        valor_mercado=_br(m.group(6)),
        as_of=as_of,
    )


def _parse_fii(line: str, as_of: Optional[str]) -> Optional[PosicaoParsed]:
    """
    FIIs: TICKER NOME TIPO QTDE PRECO_FECH PRECO_MEDIO SALDO_BRUTO
    Ex.: HGCR11 FII HGCR PAXCI FII 43 97,49 99,47 4.192,07
    """
    m = re.match(
        r"^([A-Z]{4,6}\d{0,2})\s+(.+?)\s+(FII|FIA|FC|FIC|FIDC)\s+(\d+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$",
        line,
    )
    if not m:
        return None
    return PosicaoParsed(
        ticker=m.group(1),
        nome=m.group(2).strip(),
        classe="FII",
        quantidade=float(m.group(4)),
        preco_fechamento=_br(m.group(5)),
        preco_medio=_br(m.group(6)),
        valor_mercado=_br(m.group(7)),
        as_of=as_of,
    )


_TESOURO_NOME: dict[str, str] = {
    "LFT":    "Tesouro Selic",
    "LTN":    "Tesouro Prefixado",
    "NTNB-P": "Tesouro IPCA+",
    "NTNB":   "Tesouro IPCA+ com Juros Semestrais",
    "NTN-B":  "Tesouro IPCA+ com Juros Semestrais",
    "NTN-F":  "Tesouro Prefixado com Juros Semestrais",
}


def _parse_tesouro(line: str, as_of: Optional[str]) -> Optional[PosicaoParsed]:
    """
    LFT/LTN/NTNB-P EMISSAO VENCIMENTO ... TAXA QTDE PRECO SALDO_BRUTO IR IOF SALDO_LIQ
    Extrai os últimos 5 números (antes do bloco IR/IOF/liq): qtde, preco, saldo_bruto.
    """
    m = re.match(
        r"^(LFT|LTN|NTNB-P|NTNB|NTN-B|NTN-F)\s+\d{2}/\d{2}/\d{2}\s+(\d{2}/\d{2}/\d{2})\s+",
        line,
    )
    if not m:
        return None
    sigla = m.group(1)
    vencimento = m.group(2)
    ano = "20" + vencimento[-2:]
    nome = f"{_TESOURO_NOME.get(sigla, sigla)} {ano}"

    nums = re.findall(r"[\d.,]+", line[m.end():])
    if len(nums) < 5:
        return None
    try:
        qtde        = _br(nums[-5])
        preco       = _br(nums[-4])
        saldo_bruto = _br(nums[-3])
    except (ValueError, IndexError):
        return None

    return PosicaoParsed(
        ticker=nome,
        nome=nome,
        classe="TESOURO",
        quantidade=qtde,
        preco_medio=preco,
        preco_fechamento=preco,
        valor_mercado=saldo_bruto,
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

def parse_btg_text(text: str) -> list[PosicaoParsed]:
    """
    Parseia texto copiado do extrato PDF do BTG.
    Retorna lista de PosicaoParsed (posições encontradas nas seções de Posição).
    """
    as_of: Optional[str] = None
    m = re.search(r"Período de \S+ a (\d{2}/\d{2}/\d{2})", text)
    if m:
        d, mo, y = m.group(1).split("/")
        as_of = f"20{y}-{mo}-{d}"

    lines = [ln.strip() for ln in text.splitlines()]
    positions: list[PosicaoParsed] = []
    section: Optional[str] = None

    for line in lines:
        if not line:
            continue

        # Saída de seção tem prioridade mas seção nova a sobrescreve
        is_exit = any(ex in line for ex in _SECTION_EXITS)
        new_section: Optional[str] = None
        for marker, sec in _SECTION_STARTS.items():
            if marker in line:
                new_section = sec
                break

        if new_section:
            section = new_section
            continue
        if is_exit:
            section = None
            continue
        if section is None or _is_noise(line):
            continue

        pos: Optional[PosicaoParsed] = None
        if section == "acoes":
            pos = _parse_rv(line, "ACAO", as_of)
        elif section == "etf":
            pos = _parse_rv(line, "ETF", as_of)
        elif section == "fiis":
            pos = _parse_fii(line, as_of)
        elif section == "tesouro":
            pos = _parse_tesouro(line, as_of)

        if pos:
            positions.append(pos)

    return positions
