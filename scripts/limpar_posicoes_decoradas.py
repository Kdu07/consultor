"""
Relatório e limpeza das posições com código decorado por '*'.

De onde elas vêm: extratos de período aberto decoram o ticker ('BBAS3*', 'LFT* ') e,
antes do parser v3, a decoração contaminava `chave_externa` — a mesma posição ganhou duas
linhas (uma limpa, uma decorada), quebrou o yfinance e o casamento de proventos.

O reparo de verdade é o REIMPORT (docs/PLANO_CONFIABILIDADE.md): reenviar o XLSX mais
recente pelo chat reativa as chaves limpas e a reconciliação desativa as decoradas. Este
script é o passo opcional de higiene DEPOIS disso: apagar as linhas inativas decoradas
que sobraram no banco.

Regras:
  - SEMPRE relata tudo o que achou (ativas e inativas) antes de qualquer coisa.
  - Só apaga as INATIVAS decoradas, e só com a flag explícita --apagar.
  - NUNCA toca em posição ativa: decorada ativa é sinal de que o reimport pelo chat
    ainda não foi feito — o script orienta e sai.

Uso (local, ou em produção via `fly ssh console -C "python scripts/limpar_posicoes_decoradas.py"`):
    python scripts/limpar_posicoes_decoradas.py            # só relata, não muda nada
    python scripts/limpar_posicoes_decoradas.py --apagar   # apaga as inativas decoradas
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:  # console Windows em cp1252 não pode derrubar o relatório
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import Session, select  # noqa: E402

from app.database import engine  # noqa: E402
from app.models.posicao import Posicao  # noqa: E402


def _decorada(p: Posicao) -> bool:
    return "*" in (p.chave_externa or "") or "*" in (p.ticker or "")


def _linha(p: Posicao) -> str:
    return (
        f"  id={p.id:<4} {'ATIVA  ' if p.ativo else 'inativa'}  "
        f"classe={p.classe.value:<7} ticker={p.ticker or '-':<12} "
        f"chave={p.chave_externa or '-'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Relata (e, com --apagar, remove) posições inativas com '*' no código."
    )
    parser.add_argument(
        "--apagar",
        action="store_true",
        help="Apaga as posições INATIVAS decoradas. Sem a flag, o script só relata.",
    )
    args = parser.parse_args(argv)

    with Session(engine) as session:
        decoradas = [p for p in session.exec(select(Posicao)).all() if _decorada(p)]
        ativas = [p for p in decoradas if p.ativo]
        inativas = [p for p in decoradas if not p.ativo]

        if not decoradas:
            print("Nenhuma posição com '*' em chave_externa ou ticker — nada a fazer.")
            return 0

        print(f"{len(decoradas)} posição(ões) decorada(s) com '*': "
              f"{len(ativas)} ativa(s), {len(inativas)} inativa(s).\n")
        for p in sorted(decoradas, key=lambda p: (not p.ativo, p.id or 0)):
            print(_linha(p))

        if ativas:
            print(
                f"\nATENÇÃO: {len(ativas)} posição(ões) decorada(s) ainda ATIVA(S). "
                "Este script não mexe nelas: reenvie o XLSX mais recente pelo CHAT — o "
                "import reativa as chaves limpas e desativa as decoradas "
                "(docs/PLANO_CONFIABILIDADE.md, passo A). Depois rode o script de novo."
            )

        if not inativas:
            print("\nNenhuma inativa decorada para apagar.")
            return 0

        if not args.apagar:
            print(
                f"\nNada foi apagado. Para remover as {len(inativas)} inativa(s) "
                "decorada(s) acima, rode de novo com --apagar."
            )
            return 0

        for p in inativas:
            session.delete(p)
        session.commit()
        print(f"\n{len(inativas)} posição(ões) inativa(s) decorada(s) apagada(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
