"""Testa acesso às fontes RSS de notícias."""
import asyncio
import sys
import xml.etree.ElementTree as ET
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import httpx

URLS = [
    ("google_petr4", "https://news.google.com/rss/search?q=PETR4+acoes&hl=pt-BR&gl=BR&ceid=BR:pt-BR"),
    ("infomoney",    "https://feeds.infomoney.com.br/mercados/"),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; consultor-app/0.1)"}


async def main():
    async with httpx.AsyncClient(timeout=12.0, headers=HEADERS, follow_redirects=True) as client:
        for name, url in URLS:
            print(f"\n=== {name} ===")
            try:
                r = await client.get(url)
                print(f"Status: {r.status_code} | {len(r.text)} chars")
                print(f"Content-Type: {r.headers.get('content-type', '?')}")
                # Tenta parsear XML
                try:
                    root = ET.fromstring(r.text)
                    items = root.findall(".//item")
                    print(f"Items RSS: {len(items)}")
                    for item in items[:3]:
                        title = item.findtext("title", "")
                        print(f"  - {title[:80]}")
                except ET.ParseError as pe:
                    print(f"XML parse error: {pe}")
                    print(r.text[:200])
            except Exception as e:
                print(f"ERRO: {type(e).__name__}: {e}")


asyncio.run(main())
