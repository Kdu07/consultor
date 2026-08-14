"""Testa o fluxo completo da Fase 2 via API local."""
import json
import sys
import urllib.request
from pathlib import Path

# Força UTF-8 no stdout para não quebrar com emojis no console Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
SESSION = "fase2-test"


def chat(message: str) -> dict:
    payload = json.dumps({"message": message, "session_id": SESSION}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def show(label: str, data: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  iters={data['iterations']} | {data['tokens_input']}in/{data['tokens_output']}out | ~US${data['cost_usd']:.4f}")
    print(f"{'='*60}")
    print(data["reply"][:1500])
    if len(data["reply"]) > 1500:
        print(f"  ... [{len(data['reply'])-1500} chars omitidos]")


# ── Teste 1: import ──────────────────────────────────────────────────
# O XLSX vai por upload (o binário nunca passa pelo chat) e fica em staging;
# o agente então chama importar_extrato() sem argumentos.
import httpx  # noqa: E402

XLSX = Path(sys.argv[1] if len(sys.argv) > 1 else "uploads/001234567.xlsx")
if not XLSX.exists():
    sys.exit(f"Extrato nao encontrado: {XLSX}. Passe o caminho do XLSX como argumento.")

print(f"\n>>> Enviando {XLSX.name} para POST /extrato/upload...")
with XLSX.open("rb") as fh:
    up = httpx.post(f"{BASE}/extrato/upload", files={"arquivo": (XLSX.name, fh)}, timeout=60)
up.raise_for_status()
preview = up.json()
print(f"    {preview['total_posicoes']} posicoes | ref {preview['data_referencia']} "
      f"| checksum_ok={preview['checagem_totais']['ok']}")

r1 = chat("Importe o extrato que acabei de enviar.")
show("TESTE 1: importar_extrato (preview)", r1)

# ── Teste 2: confirmação ──────────────────────────────────────────────
print("\n>>> Confirmando com 'sim'...")
r2 = chat("sim, pode gravar")
show("TESTE 2: gravar_posicoes (confirmacao)", r2)

# ── Teste 3: desvio ───────────────────────────────────────────────────
print("\n>>> Calculando desvio...")
r3 = chat("minha carteira saiu do alvo? calcule o desvio")
show("TESTE 3: calcular_desvio", r3)

print("\nFASE 2 OK" if not r3.get("anomaly") else "\nANOMALIA DETECTADA")
