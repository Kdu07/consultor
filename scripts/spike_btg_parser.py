"""
Spike CLI — parser de texto colado do extrato PDF do BTG.

Uso:
    python scripts/spike_btg_parser.py < data/extrato.txt
    python scripts/spike_btg_parser.py data/extrato.txt

A lógica de parsing vive em app/tools/btg_parser.py.
Este script é apenas um wrapper CLI para inspeção e debug.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

# Garante que o pacote app esteja no path quando rodado como script standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.btg_parser import parse_btg_text  # noqa: E402


def _print_preview(positions) -> None:
    print(f"\n{'='*70}")
    print(f"  PREVIEW — {len(positions)} posicoes extraidas")
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
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    positions = parse_btg_text(text)
    _print_preview(positions)
    print(json.dumps([asdict(p) for p in positions], ensure_ascii=False, indent=2))
