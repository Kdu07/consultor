"""
Spike — parser de texto colado do extrato PDF do BTG Pactual.

Uso:
    python scripts/spike_btg_parser.py < data/extrato.txt
    python scripts/spike_btg_parser.py data/extrato.txt

Formato testado: "Extrato da Conta Investimento" (Período 05/2026).
Seções suportadas: Ações, ETF, Fundos Listados (FIIs), Tesouro Direto (LFT, LTN, NTNB-P).
Ignora: RF privada (CDB/LCI/LCA) — sem tabela de posição estruturada no extrato.

Saída do spike: JSON com as posições extraídas para revisão visual.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Modelo de posição parseada
# ---------------------------------------------------------------------------

@dataclass
class PosicaoParsed:
    ticker: str           # ex.: "PETR4", "Tesouro Selic 2028"
    nome: str             # descrição longa do ativo
    classe: str           # ACAO | ETF | FII | TESOURO
    quantidade: float
    preco_medio: Optional[float]     # preço médio de aquisição (RV) ou unitário (Tesouro)
    valor_mercado: float             # saldo bruto na data do extrato
    preco_fechamento: Optional[float]  # preço de fechamento na data do extrato (RV)
    as_of: Optional[str]             # data de referência (YYYY-MM-DD)


# ---------------------------------------------------------------------------
# Helpers de número
# ---------------------------------------------------------------------------

def _br(s: str) -> float:
    """Converte número brasileiro para float: '19.100,18' → 19100.18"""
    return float(s.strip().replace(".", "").replace(",", "."))


# ---------------------------------------------------------------------------
# Mapa de seções
# ---------------------------------------------------------------------------

# Chave: substring que identifica início de seção; valor: nome interno
_SECTION_STARTS: dict[str, str] = {
    "Renda variável - Posição - Ações":           "acoes",
    "Renda variável - Posição - ETF":             "etf",
    "Renda variável - Posição - Fundos Listados": "fiis",
    "Renda fixa - Posição - TESOURO DIRETO":      "tesouro",  # qualquer subtipo TD
}

# Substrings que encerram qualquer seção ativa
_SECTION_EXITS: list[str] = [
    "Renda variável - Movimentação",
    "Renda fixa - Detalhamento",
    "Renda fixa - Movimentação",
    "Renda fixa - Posição Consolidada",
    "Conta corrente",
    "Valores em trânsito",
    "Distribuição Setorial",
]

# Prefixos de linhas que são sempre ruído (cabeçalhos, rodapés, SAC)
_NOISE_PREFIXES: tuple[str, ...] = (
    "Emissor", "Código", "SAC:", "Extrato da", "Período de",
    "Emitido em", "CARLOS", "Conta invest", "CPF", "RUA ",
    "índice", "Leitura", "Total", "RENDA", "Sumário", "Mercados",
    "Renda Variável", "Renda Fixa", "Conta Corrente", "VALORES EM",
    "Perfil de Risco", "Disclaimers", "Geral", "Suitability",
    "Fale Conosco", "Distribui",
)


def _is_noise(line: str) -> bool:
    if not line:
        return True
    if line.startswith(_NOISE_PREFIXES):
        return True
    # Linhas puramente numéricas/subtotais (ex.: "5.722,04 56,15 - 5.665,89")
    if re.match(r'^[\d.,\s\-]+$', line):
        return True
    # Linhas de emissor do Tesouro
    if "BACEN" in line or "BRASIL - RJ" in line:
        return True
    return False


# ---------------------------------------------------------------------------
# Parsers de linha por seção
# ---------------------------------------------------------------------------

def _parse_rv(line: str, classe: str, as_of: Optional[str]) -> Optional[PosicaoParsed]:
    """
    Ações e ETFs:
        TICKER NOME QTDE PRECO_FECH PRECO_MEDIO SALDO_BRUTO
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
    Fundos Listados (FII):
        TICKER NOME TIPO QTDE PRECO_FECH PRECO_MEDIO SALDO_BRUTO
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


# Mapeamento sigla BTG → nome Tesouro Transparente
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
    LFT/LTN/NTNB-P ... QTDE PRECO SALDO_BRUTO IR IOF SALDO_LIQ
    Ex.: LFT 05/01/22 01/03/28 Não - - SELIC + 0,04% 0,18 19.100,180000 3.438,03 37,31 - 3.400,72

    Extraímos da direita: os últimos 3 números relevantes (antes dos 2 finais IR/saldo_liq)
    são: quantidade, preço, saldo_bruto.
    """
    m = re.match(
        r"^(LFT|LTN|NTNB-P|NTNB|NTN-B|NTN-F)\s+\d{2}/\d{2}/\d{2}\s+(\d{2}/\d{2}/\d{2})\s+",
        line,
    )
    if not m:
        return None

    sigla = m.group(1)
    vencimento = m.group(2)  # ex.: "01/03/28"
    ano = "20" + vencimento[-2:]
    nome_base = _TESOURO_NOME.get(sigla, sigla)
    nome = f"{nome_base} {ano}"

    rest = line[m.end():]
    # Extrai todos os números do restante da linha
    nums = re.findall(r"[\d.,]+", rest)
    # Estrutura: [taxa_num?, qtde, preco_6dec, saldo_bruto, IR, saldo_liq]
    # Pegamos os 5 últimos: qtde, preco, saldo_bruto, IR, saldo_liq
    if len(nums) < 5:
        return None

    try:
        qtde        = _br(nums[-5])
        preco       = _br(nums[-4])
        saldo_bruto = _br(nums[-3])
    except (ValueError, IndexError):
        return None

    return PosicaoParsed(
        ticker=nome,           # ticker = nome descritivo (usado pelo TesouroProvider)
        nome=nome,
        classe="TESOURO",
        quantidade=qtde,
        preco_medio=preco,     # preço "médio" aqui é o preço unitário do Tesouro na data
        preco_fechamento=preco,
        valor_mercado=saldo_bruto,
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# Parser principal (state machine)
# ---------------------------------------------------------------------------

def parse_btg_text(text: str) -> list[PosicaoParsed]:
    """
    Parseia texto colado do extrato PDF do BTG.
    Retorna lista de posições extraídas.
    """
    # Data de referência: "Período de 01/05/26 a 31/05/26"
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

        # 1. Verificar se é saída de seção (antes de verificar entrada)
        is_exit = any(ex in line for ex in _SECTION_EXITS)
        # 2. Verificar se é entrada de nova seção
        new_section: Optional[str] = None
        for marker, sec in _SECTION_STARTS.items():
            if marker in line:
                new_section = sec
                break

        if new_section:
            section = new_section
            continue                # pula a própria linha de cabeçalho de seção
        if is_exit:
            section = None
            continue

        if section is None:
            continue
        if _is_noise(line):
            continue

        # 3. Parsear linha conforme seção ativa
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


# ---------------------------------------------------------------------------
# CLI do spike
# ---------------------------------------------------------------------------

def _print_preview(positions: list[PosicaoParsed]) -> None:
    print(f"\n{'='*70}")
    print(f"  PREVIEW — {len(positions)} posições extraídas")
    print(f"{'='*70}")
    total = 0.0
    for p in positions:
        ticker_col = f"{p.ticker:<25}"
        classe_col = f"{p.classe:<8}"
        qtde_col   = f"qtde={p.quantidade:<8.4g}"
        vm_col     = f"R$ {p.valor_mercado:>10,.2f}"
        pm_col     = f"p.medio={p.preco_medio:<10.2f}" if p.preco_medio else ""
        print(f"  {ticker_col} {classe_col} {qtde_col} {vm_col}  {pm_col}")
        total += p.valor_mercado
    print(f"{'='*70}")
    print(f"  TOTAL EXTRAIDO: R$ {total:,.2f}")
    print(f"  Data de referencia: {positions[0].as_of if positions else 'n/a'}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    positions = parse_btg_text(text)
    _print_preview(positions)

    # JSON completo para inspeção
    print(json.dumps([asdict(p) for p in positions], ensure_ascii=False, indent=2))
