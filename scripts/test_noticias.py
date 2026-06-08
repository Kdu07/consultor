"""Testa a tool de noticias diretamente (sem loop do agente)."""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app.tools.noticias import tool_noticias

async def main():
    for query in ["PETR4", "Selic", "mercado"]:
        print(f"\n=== noticias('{query}') ===")
        result = await tool_noticias(query)
        if "error" in result:
            print(f"ERRO: {result['error']}")
        else:
            print(f"OK: {result['total']} manchetes | cached={result['is_cached']}")
            for m in result["manchetes"][:3]:
                print(f"  [{m['fonte']}] {m['titulo'][:80]}")

asyncio.run(main())
