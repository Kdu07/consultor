"""
Gravação segura (plano "Confiabilidade dos extratos", Fase 3).

O que estes testes protegem:
  - veredito "erro" do validador BLOQUEIA gravar_posicoes e o staging permanece;
  - veredito "aviso" grava e repassa as mensagens em result["avisos"];
  - staging sem `validacao` (payload antigo, gravação manual) grava como sempre;
  - erro por item → rollback TOTAL (nada parcial no banco), com e sem staging;
  - lote: item com erro fica selecionavel=False e a confirmação herda o bloqueio;
  - ExtratoResumo expõe validacao_veredito/validacao_erros (None/0 em payload antigo).

Os defeitos são injetados pelo gerador sintético: desalinhar_sumario={"Renda Variável": X}
desloca o Sumário em X reais em relação aos blocos da aba — X=50 estoura a tolerância de
R$ 1,00 (erro), X=0,50 fica entre R$ 0,05 e R$ 1,00 (aviso).
"""
import json
from datetime import date

import pytest

from tests.gerador_extrato import TOTAL_POSICOES_FIXTURE, EspecExtrato, gerar
from tests.planilhas import bytes_fixture, payload_mes

ERRO_RV = {"Renda Variável": 50.0}     # > R$ 1,00 → check V2 reprova
AVISO_RV = {"Renda Variável": 0.50}    # entre R$ 0,05 e R$ 1,00 → aviso

JULHO_OK = bytes_fixture()
JULHO_ERRO = gerar(EspecExtrato(desalinhar_sumario=ERRO_RV))
JUNHO_ERRO = gerar(EspecExtrato(inicio=date(2026, 6, 1), fim=date(2026, 6, 30),
                                desalinhar_sumario=ERRO_RV))
MAIO_AVISO = gerar(EspecExtrato(inicio=date(2026, 5, 1), fim=date(2026, 5, 31),
                                desalinhar_sumario=AVISO_RV))


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Aponta o app para um SQLite descartável e recria o schema."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")
    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    import app.models  # noqa: F401 — registra as tabelas no metadata
    import app.tools.gravar as gravar_mod
    from sqlmodel import SQLModel

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(gravar_mod, "engine", engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def staging_limpo():
    from app.tools import extrato_lote, extrato_staging

    extrato_staging.clear()
    extrato_lote.descartar()
    yield
    extrato_staging.clear()
    extrato_lote.descartar()


@pytest.fixture
def cliente(banco):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.extrato import router as extrato
    from app.api.extrato_lote import router as lote

    app = FastAPI()
    app.include_router(extrato)
    app.include_router(lote)
    return TestClient(app)


def _staging(conteudo: bytes, nome: str = "x.xlsx") -> dict:
    """Reproduz o que POST /extrato/upload deixa no staging (bruto = anexar_validacao)."""
    from sqlmodel import Session
    import app.database as database
    from app.tools import extrato_staging
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.extrato import montar_preview
    from app.tools.extrato_validacao import anexar_validacao

    extrato = parse_btg_xlsx(conteudo)
    with Session(database.engine) as session:
        bruto = anexar_validacao(extrato, session)
    preview = montar_preview(extrato, nome, validacao=bruto["validacao"])
    extrato_staging.set_preview(preview, nome, bruto=bruto)
    return preview


def _posicoes(engine) -> list:
    from sqlmodel import Session, select
    from app.models.posicao import Posicao

    with Session(engine) as s:
        return s.exec(select(Posicao)).all()


def _arquivados(engine) -> list[str]:
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado

    with Session(engine) as s:
        return sorted(e.data_referencia.isoformat()
                      for e in s.exec(select(ExtratoImportado)).all())


# ---------------------------------------------------------------------------
# Upload → staging → gravar_posicoes
# ---------------------------------------------------------------------------

async def test_upload_com_erro_bloqueia_gravacao_e_mantem_staging(banco, cliente):
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    resp = cliente.post("/extrato/upload", files={"arquivo": ("x.xlsx", JULHO_ERRO)})
    assert resp.status_code == 200, resp.text
    preview = resp.json()

    # Campos aditivos do preview
    assert preview["validacao"]["veredito"] == "erro"
    assert preview["validacao"]["erros"], "o resumo compacto carrega as mensagens"
    assert "checks" not in preview["validacao"], "a lista completa não vai ao modelo"
    assert preview["periodo"]["inicio"] == "2026-07-01"
    assert preview["periodo"]["fim"] == preview["data_referencia"]
    assert preview["periodo"]["mensal"] is True
    assert "VALIDAÇÃO REPROVOU" in preview["aviso"]

    # O bruto do staging é o payload de anexar_validacao
    assert extrato_staging.get()["bruto"]["validacao"]["veredito"] == "erro"

    resultado = await tool_gravar_posicoes()

    assert "error" in resultado, resultado
    assert "V2_RV_TOTAL" in resultado["error"], "cita o check reprovado"
    assert "Nada foi gravado" in resultado["error"]
    # staging MANTIDO: o usuário pode perguntar sobre o que falhou
    assert extrato_staging.get() is not None
    assert _posicoes(banco) == []
    assert _arquivados(banco) == []


async def test_aviso_grava_e_repassa_as_mensagens(banco):
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    _staging(gerar(EspecExtrato(desalinhar_sumario=AVISO_RV)))
    resultado = await tool_gravar_posicoes()

    assert "error" not in resultado, resultado
    assert resultado["total_gravadas"] == TOTAL_POSICOES_FIXTURE
    assert any("V2_RV_TOTAL" in a for a in resultado["avisos"]), resultado.get("avisos")
    assert extrato_staging.get() is None, "sucesso consome o staging"

    # O mês arquivado carrega a validação inteira (irmã de checagem)
    with Session(banco) as s:
        payload = json.loads(s.exec(select(ExtratoImportado)).one().payload_json)
    assert payload["validacao"]["veredito"] == "aviso"
    assert "validacao" not in (payload.get("checagem") or {})


async def test_staging_sem_validacao_grava_como_hoje(banco):
    """Staging antigo/manual (bruto sem `validacao`) não pode passar a falhar."""
    from app.tools import extrato_staging
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.extrato import montar_preview
    from app.tools.gravar import tool_gravar_posicoes

    extrato = parse_btg_xlsx(JULHO_OK)
    preview = montar_preview(extrato, "antigo.xlsx")
    extrato_staging.set_preview(preview, "antigo.xlsx", bruto=extrato.to_dict())

    resultado = await tool_gravar_posicoes()

    assert "error" not in resultado, resultado
    assert resultado["total_gravadas"] == TOTAL_POSICOES_FIXTURE
    assert resultado["extrato_arquivado"]["acao"] == "criado"


# ---------------------------------------------------------------------------
# Atomicidade: erro por item → rollback total
# ---------------------------------------------------------------------------

async def test_erro_por_item_na_gravacao_manual_faz_rollback_total(banco):
    from app.tools.gravar import tool_gravar_posicoes

    resultado = await tool_gravar_posicoes([
        {"ticker": "PETR4", "nome": "PETROBRAS PN", "classe": "ACAO",
         "quantidade": 100, "valor_mercado": 3800.0},
        {"nome": "", "classe": "ACAO", "quantidade": 1, "valor_mercado": 10.0},
    ])

    assert "error" in resultado, resultado
    assert "sem nome" in resultado["error"]
    assert _posicoes(banco) == [], "a posição válida do mesmo lote não pode sobrar no banco"


async def test_erro_por_item_com_staging_nao_grava_nem_arquiva_e_mantem_staging(banco):
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    preview = _staging(JULHO_OK)
    preview["posicoes"][0]["nome"] = ""   # item inválido no meio do lote completo

    resultado = await tool_gravar_posicoes()

    assert "error" in resultado, resultado
    assert "sem nome" in resultado["error"]
    assert extrato_staging.get() is not None, "staging só é limpo em sucesso"
    assert _posicoes(banco) == []
    assert _arquivados(banco) == []


# ---------------------------------------------------------------------------
# Lote
# ---------------------------------------------------------------------------

async def test_lote_bloqueia_item_com_erro_e_confirmar_herda_o_bloqueio(banco, cliente):
    from app.tools.gravar import tool_gravar_posicoes

    # Carteira = julho (corte 2026-07-31), pelo caminho do chat.
    _staging(JULHO_OK)
    await tool_gravar_posicoes()

    files = [("arquivos", ("junho.xlsx", JUNHO_ERRO)), ("arquivos", ("maio.xlsx", MAIO_AVISO))]
    lote = cliente.post("/extrato/lote", files=files).json()
    junho, maio = lote["itens"]

    assert junho["status"] == "novo", "anterior ao corte: seria arquivável sem o erro"
    assert junho["selecionavel"] is False
    assert junho["selecionado_padrao"] is False
    assert junho["validacao"]["veredito"] == "erro"
    assert "V2_RV_TOTAL" in junho["mensagem"], "mensagem = primeiro erro da validação"

    assert maio["selecionavel"] is True, "aviso não bloqueia"
    assert maio["selecionado_padrao"] is False, "aviso desmarca por padrão"
    assert maio["validacao"]["veredito"] == "aviso"
    assert any("V2_RV_TOTAL" in a for a in maio["avisos"])

    corpo = cliente.post(
        f"/extrato/lote/{lote['id']}/confirmar",
        json={"datas": ["2026-06-30", "2026-05-31"]},
    ).json()

    assert [a["data_referencia"] for a in corpo["arquivados"]] == ["2026-05-31"]
    assert [(r["data_referencia"], r["motivo"]) for r in corpo["recusados"]] == [
        ("2026-06-30", "validacao_erro")
    ]
    assert _arquivados(banco) == ["2026-05-31", "2026-07-31"]


# ---------------------------------------------------------------------------
# Histórico
# ---------------------------------------------------------------------------

async def test_historico_expoe_o_veredito_da_validacao(banco, cliente):
    from sqlmodel import Session
    from app.models.extrato import ExtratoImportado
    from app.tools.gravar import tool_gravar_posicoes

    _staging(JULHO_OK)
    await tool_gravar_posicoes()

    # Um mês antigo, arquivado antes do validador (payload v2, sem `validacao`).
    with Session(banco) as s:
        s.add(ExtratoImportado(
            data_referencia=date(2026, 5, 31),
            payload_json=json.dumps(payload_mes("2026-05-31", 100_000.0, 101_000.0)),
        ))
        s.commit()

    linhas = {l["data_referencia"]: l for l in cliente.get("/extrato/historico").json()}

    assert linhas["2026-07-31"]["validacao_veredito"] == "ok"
    assert linhas["2026-07-31"]["validacao_erros"] == 0
    assert linhas["2026-05-31"]["validacao_veredito"] is None, "payload anterior ao validador"
    assert linhas["2026-05-31"]["validacao_erros"] == 0
