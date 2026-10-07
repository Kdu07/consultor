"""
Smoke local do parser + validador sobre extratos XLSX reais — somente leitura.

Para que serve: antes de um deploy, rodar os extratos baixados do BTG pelo caminho
completo (parse_btg_xlsx → anexar_validacao) e ver a tabela de checks de cada um.
Critério de pronto: todo extrato real sai 'ok' ou 'aviso', e os avisos são as
inconsistências conhecidas do próprio BTG — qualquer 'erro' é bug nosso.

Privacidade (o arquivo do BTG tem nome, CPF e conta; a saída deste script não):
  - o nome do arquivo sai mascarado (o do BTG é o número da conta);
  - nada da Capa além das datas; nunca o nome do titular;
  - a tabela padrão mostra id, severidade, diferença e detalhe — os campos
    esperado/obtido (saldos da carteira) só aparecem com --valores, assim a saída
    padrão pode ser colada em qualquer lugar;
  - não grava nada em disco.

Uso:
    .venv\\Scripts\\python.exe scripts/validar_extratos_locais.py a.xlsx [b.xlsx ...] [--valores]

Sai com código 1 se algum extrato não abrir ou terminar com veredito 'erro'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.tools.btg_xlsx_parser import (  # noqa: E402
    ExtratoParseError,
    mascarar_nome_arquivo,
    parse_btg_xlsx,
)
from app.tools.extrato_validacao import anexar_validacao  # noqa: E402


def _imprimir(indice: int, nome: str, payload: dict, mostrar_valores: bool) -> str:
    validacao = payload.get("validacao") or {}
    veredito = validacao.get("veredito", "?")
    meta = (payload.get("sumario") or {}).get("meta") or {}
    print(f"\n{'=' * 72}")
    print(f"#{indice} {nome}  período {meta.get('periodo_inicio') or '?'} → "
          f"{payload.get('data_referencia')}  —  veredito: {veredito.upper()}")

    for c in validacao.get("checks") or []:
        dif = c.get("diferenca")
        linha = f"  {c.get('severidade', '?'):<13} {c.get('id', '?'):<30} dif={dif if dif is not None else '—'}"
        if mostrar_valores:
            linha += f"  esperado={c.get('esperado')} obtido={c.get('obtido')}"
        if c.get("severidade") not in ("ok",) and c.get("detalhe"):
            linha += f"  [{c['detalhe'][:110]}]"
        print(linha)

    avisos_parser = payload.get("avisos_parser") or []
    ignoradas = payload.get("linhas_ignoradas") or []
    print(f"  parser: {len(avisos_parser)} aviso(s) "
          f"{sorted({a.get('tipo') for a in avisos_parser}) if avisos_parser else ''}; "
          f"{len(ignoradas)} linha(s) ignorada(s)")
    if mostrar_valores:
        for msg in (validacao.get("erros") or []):
            print(f"  ERRO : {msg}")
        for msg in (validacao.get("avisos") or []):
            print(f"  aviso: {msg}")
    return veredito


def main() -> int:
    argumentos = sys.argv[1:]
    mostrar_valores = "--valores" in argumentos
    caminhos = [Path(a) for a in argumentos if not a.startswith("--")]
    if not caminhos:
        print(__doc__)
        return 1

    codigo = 0
    for i, caminho in enumerate(caminhos, 1):
        nome = mascarar_nome_arquivo(caminho.name) or "?"
        if not caminho.exists():
            print(f"\n#{i} {nome}: arquivo não encontrado")
            codigo = 1
            continue
        try:
            extrato = parse_btg_xlsx(caminho.read_bytes())
        except ExtratoParseError as e:
            print(f"\n#{i} {nome}: não parseou — {e}")
            codigo = 1
            continue
        # Sem session de propósito: smoke é local e não toca banco (V7 fica de fora).
        payload = anexar_validacao(extrato)
        if _imprimir(i, nome, payload, mostrar_valores) == "erro":
            codigo = 1

    print("\nRevise antes de colar em qualquer lugar: a saída não deve ter nome nem saldo"
          + (" — ATENÇÃO: --valores expõe os saldos." if mostrar_valores else "."))
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
