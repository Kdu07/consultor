"""
Prepara o carteira.db local para ser enviado ao volume do Fly (PLANO_DEPLOY_FLY, passo 7).

O problema: com WAL ligado, as últimas escritas moram em carteira.db-wal, não no
.db. Copiar só o .db perderia esses dados sem avisar. O checkpoint TRUNCATE
dobra o -wal de volta para dentro do arquivo principal e o zera.

Funciona nos dois casos — banco em WAL ou em journal clássico.

    uv run python scripts/preparar_db_para_upload.py
"""
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "data" / "carteira.db"
BACKUPS = RAIZ / "backups"


def main() -> int:
    if not BANCO.exists():
        print(f"[erro] não encontrei {BANCO}")
        return 1

    con = sqlite3.connect(BANCO)
    try:
        modo = con.execute("PRAGMA journal_mode").fetchone()[0]
        print(f"journal_mode: {modo}")

        bloqueados, paginas, movidas = con.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        if bloqueados:
            print(
                "[erro] o checkpoint não completou — há outro processo com o banco "
                "aberto (o uvicorn está rodando?). Feche e rode de novo."
            )
            return 1
        print(f"checkpoint ok — {paginas} páginas no WAL, {movidas} aplicadas")

        integridade = con.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"integrity_check: {integridade}")
        if integridade != "ok":
            return 1
    finally:
        con.close()

    sobra = BANCO.with_name(BANCO.name + "-wal")
    if sobra.exists() and sobra.stat().st_size > 0:
        print(f"[aviso] {sobra.name} ainda tem {sobra.stat().st_size} bytes")

    BACKUPS.mkdir(exist_ok=True)
    copia = BACKUPS / f"carteira-pre-fly-{date.today():%Y%m%d}.db"
    shutil.copy2(BANCO, copia)

    print(f"\nbackup: {copia}")
    print(f"pronto para enviar: {BANCO} ({BANCO.stat().st_size / 1024:.0f} KB)")
    # Máquina RODANDO: o ssh/sftp não fala com máquina parada. Sobe com nome temporário
    # e troca levando junto o -wal e o -shm do banco antigo (PLANO_DEPLOY_FLY, passo 7).
    print("\nNo Fly (com a máquina rodando):")
    print("  fly ssh sftp put data/carteira.db /data/carteira.novo.db")
    print("  fly ssh console -C \"sh -c 'rm -f /data/carteira.db /data/carteira.db-wal "
          "/data/carteira.db-shm && mv /data/carteira.novo.db /data/carteira.db'\"")
    print("  fly machine restart <ID>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
