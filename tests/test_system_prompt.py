"""
System prompt do agente: a parte fixa chega inteira ao modelo, e em bloco com cache.

O bug que isto fecha: o .md cita o marcador "=== CONTEXTO DINÂMICO ===" na nota "Como
usar" da linha 3, e o builder cortava no primeiro achado. De 06/2026 a 10/2026 o modelo
recebeu 101 caracteres de parte fixa — sem persona, guardrails nem princípios das tools.
"""
import pytest


def test_parte_fixa_chega_inteira():
    from app.agent.system_prompt import _MARKER, _fixed_part

    fixa = _fixed_part()
    assert len(fixa) > 15_000, f"parte fixa com {len(fixa)} caracteres — cortou cedo"
    for trecho in ("## 12. O que você nunca faz", "desempenho_carteira", "gravar_posicoes"):
        assert trecho in fixa
    assert not any(linha.strip() == _MARKER for linha in fixa.splitlines()), \
        "o marcador sozinho na linha é onde a parte fixa termina"


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")
    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    import app.agent.system_prompt as sp
    import app.models  # noqa: F401
    from sqlmodel import SQLModel

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(sp, "engine", engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    get_settings.cache_clear()


def test_blocos_com_cache_na_parte_fixa(banco):
    from app.agent.system_prompt import _MARKER, _fixed_part, build_system_blocks, build_system_prompt

    fixo, dinamico = build_system_blocks()
    assert fixo["cache_control"] == {"type": "ephemeral"}
    assert fixo["text"] == _fixed_part()
    assert "cache_control" not in dinamico, "o que muda fica depois do ponto de cache"
    assert dinamico["text"].startswith(_MARKER)
    # o texto total é o mesmo do prompt em string
    assert f"{fixo['text']}\n\n{dinamico['text']}" == build_system_prompt()


def test_custo_conta_o_cache():
    from types import SimpleNamespace
    from app.agent.loop import _calc_cost, _uso

    assert _calc_cost(1_000, 100) == pytest.approx((1_000 * 3 + 100 * 15) / 1e6)
    # gravar 6.000 no cache = 7.500 tokens de entrada; ler 6.000 = 600
    assert _calc_cost(1_000, 100, cache_gravado=6_000) == pytest.approx((8_500 * 3 + 100 * 15) / 1e6)
    assert _calc_cost(1_000, 100, cache_lido=6_000) == pytest.approx((1_600 * 3 + 100 * 15) / 1e6)

    sem_cache = SimpleNamespace(input_tokens=10, output_tokens=5)
    assert _uso(sem_cache) == (10, 5, 0, 0)
    com_cache = SimpleNamespace(input_tokens=10, output_tokens=5,
                                cache_creation_input_tokens=None, cache_read_input_tokens=7)
    assert _uso(com_cache) == (10, 5, 0, 7)
