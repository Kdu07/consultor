"""
Migração: coluna `chave_externa` na tabela `posicao`.

Identidade do papel entre extratos ('B3:BBAS3', 'TD:LFT:2031-03-01'). Sem ela o upsert
do import casa por nome, e o BTG reescreve o nome de um mês para o outro
('FII HGCR PAXCI' → 'FII HGCR PAXCI ER') — a posição antiga era abandonada e uma nova
nascia no lugar. SQLModel.metadata.create_all() cria tabelas novas, mas NÃO altera
tabela existente — daí este script.

NÃO faz backfill: a chave de um papel não é recuperável a partir do nome já gravado
(o nome de renda fixa não guarda a sigla nem o vencimento de forma confiável). As linhas
existentes ficam com chave nula e são adotadas no primeiro import — o upsert casa por
ticker/nome, como hoje, e grava a chave. Adivinhar a chave aqui é que seria arriscado:
uma chave errada gruda duas posições diferentes numa só.

É idempotente (checa PRAGMA table_info antes) e faz backup do banco antes de tocar
em qualquer coisa, via con.backup() — o método seguro com o banco em uso.

Uso:
    .venv\\Scripts\\python.exe scripts/migrate_posicao_chave_externa.py
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import get_settings  # noqa: E402

COLUNAS_NOVAS = {
    "chave_externa": "VARCHAR",
}

INDICES = {
    "ix_posicao_chave_externa": "CREATE INDEX IF NOT EXISTS ix_posicao_chave_externa ON posicao (chave_externa)",
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
              "(será criado já com a coluna nova na próxima subida do servidor).")
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
        for nome, ddl in INDICES.items():
            con.execute(ddl)
            print(f"Índice criado: {nome}")
        pendentes = con.execute(
            "SELECT COUNT(*) FROM posicao WHERE ativo = 1 AND chave_externa IS NULL"
        ).fetchone()[0]
    con.close()

    print(f"Migração concluída. {pendentes} posição(ões) ativa(s) sem chave — "
          "serão adotadas no próximo import do extrato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
