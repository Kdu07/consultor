"""
Migração: colunas de renda fixa na tabela `posicao` (PLANO_XLSX, Bloco 6a).

Adiciona `vencimento` e `taxa_contratada`, que passam a vir do extrato XLSX.
SQLModel.metadata.create_all() cria tabelas novas, mas NÃO altera tabela existente —
daí este script.

É idempotente (checa PRAGMA table_info antes) e faz backup do banco antes de tocar
em qualquer coisa, via con.backup() — o método seguro com o banco em uso.

Uso:
    .venv\\Scripts\\python.exe scripts/migrate_posicao_rf.py
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import get_settings  # noqa: E402

COLUNAS_NOVAS = {
    "vencimento": "DATETIME",
    "taxa_contratada": "VARCHAR",
}


def caminho_do_banco() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        sys.exit(f"Este script só migra SQLite (DATABASE_URL={url}).")
    caminho = url.split("///")[-1]
    return (RAIZ / caminho).resolve() if not Path(caminho).is_absolute() else Path(caminho)


def fazer_backup(db: Path) -> Path:
    destino_dir = RAIZ / "backups"
    destino_dir.mkdir(exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    destino = destino_dir / f"carteira-pre-migracao-{carimbo}.db"

    origem = sqlite3.connect(str(db))
    copia = sqlite3.connect(str(destino))
    with copia:
        origem.backup(copia)
    copia.close()
    origem.close()
    return destino


def main() -> int:
    db = caminho_do_banco()
    if not db.exists():
        print(f"Banco não encontrado em {db} — nada a migrar "
              "(será criado já com as colunas novas na próxima subida do servidor).")
        return 0

    con = sqlite3.connect(str(db))
    existentes = {linha[1] for linha in con.execute("PRAGMA table_info(posicao)")}
    if not existentes:
        con.close()
        print("Tabela 'posicao' ainda não existe — nada a migrar.")
        return 0

    faltando = {c: t for c, t in COLUNAS_NOVAS.items() if c not in existentes}
    if not faltando:
        con.close()
        print("Banco já migrado — nenhuma coluna a adicionar.")
        return 0

    con.close()
    backup = fazer_backup(db)
    print(f"Backup criado: {backup}")

    con = sqlite3.connect(str(db))
    with con:
        for coluna, tipo in faltando.items():
            con.execute(f"ALTER TABLE posicao ADD COLUMN {coluna} {tipo}")
            print(f"Coluna adicionada: posicao.{coluna} ({tipo})")
    con.close()

    print("Migração concluída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
