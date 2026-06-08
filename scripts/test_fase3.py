"""Testa o fluxo da Fase 3: noticias, dashboard e snapshot via API local."""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
SESSION = "fase3-test"


def get(path: str) -> dict | list:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.loads(r.read())


def post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(
        f"{BASE}{path}", data=data or None,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def chat(message: str) -> dict:
    payload = json.dumps({"message": message, "session_id": SESSION}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def show(label: str, data: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if isinstance(data, dict) and "reply" in data:
        print(f"  iters={data['iterations']} | {data['tokens_input']}in/{data['tokens_output']}out | ~US${data['cost_usd']:.4f}")
        print(data["reply"][:600])
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:600])


# ── Teste 1: dashboard ─────────────────────────────────────────────
print("\n>>> GET /dashboard")
d = get("/dashboard")
print(f"Total: R$ {d['total']:,.2f} | posicoes={len(d['posicoes'])} | ao_vivo={d['fracao_ao_vivo_pct']}%")
print(f"Por classe: {[(c['classe'], c['percentual_atual']) for c in d['por_classe'][:4]]}")

# ── Teste 2: snapshot ──────────────────────────────────────────────
print("\n>>> POST /snapshots")
snap = post("/snapshots")
print(f"Snapshot id={snap['id']} data={snap['data_referencia']} total=R${snap['valor_total']:,.2f} pos={snap['posicoes_count']}")

# ── Teste 3: noticias via agente ───────────────────────────────────
print("\n>>> noticias PETR4 via agente...")
r = chat("quais as ultimas noticias sobre PETR4?")
show("TESTE 3: noticias(PETR4)", r)

# ── Teste 4: noticias Selic ────────────────────────────────────────
print("\n>>> noticias Selic via agente...")
r2 = chat("o que esta acontecendo com a Selic e os juros no Brasil?")
show("TESTE 4: noticias(Selic)", r2)

print("\nFASE 3 OK" if not (r.get("anomaly") or r2.get("anomaly")) else "\nANOMALIA DETECTADA")
