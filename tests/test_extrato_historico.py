"""
Histórico de extratos: o import arquiva o mês em vez de sobrescrevê-lo em silêncio.

O que estes testes protegem: antes desta camada, `gravar_posicoes` fazia upsert
destrutivo na tabela Posicao e o preview — proventos, movimentações, aluguel, valores
em trânsito — morria em memória junto com o staging. Importar setembro apagava agosto.

Cobrem as três garantias da camada: o mês é arquivado inteiro, reimportar corrige em
vez de duplicar, e o snapshot sai com a data e o valor do extrato (não os de hoje).
"""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURE = Path(__file__).parent / "fixtures" / "extrato_exemplo.xlsx"


@pytest.fixture
def banco_temporario(tmp_path, monkeypatch):
    """Aponta o app para um SQLite descartável e recria o schema."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")

    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    from sqlmodel import SQLModel
    import app.models  # noqa: F401 — registra as tabelas no metadata

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    import app.tools.gravar as gravar_mod
    import app.api.extrato as extrato_api
    monkeypatch.setattr(gravar_mod, "engine", engine)
    monkeypatch.setattr(extrato_api, "engine", engine)

    yield engine
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def staging_limpo():
    from app.tools import extrato_staging

    extrato_staging.clear()
    yield
    extrato_staging.clear()


@pytest.fixture
def extrato_parseado():
    from app.tools.btg_xlsx_parser import parse_btg_xlsx

    return parse_btg_xlsx(FIXTURE.read_bytes())


@pytest.fixture
def staging_completo(extrato_parseado):
    """Reproduz o upload real: preview + bruto no staging, como POST /extrato/upload deixa."""
    from app.tools import extrato_staging
    from app.tools.extrato import montar_preview

    preview = montar_preview(extrato_parseado, "extrato_exemplo.xlsx")
    extrato_staging.set_preview(preview, "extrato_exemplo.xlsx", bruto=extrato_parseado.to_dict())
    return preview


async def test_import_arquiva_o_mes(banco_temporario, staging_completo):
    from datetime import date
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.tools.gravar import tool_gravar_posicoes

    resultado = await tool_gravar_posicoes()

    ref = date.fromisoformat(staging_completo["data_referencia"])
    assert resultado["extrato_arquivado"]["acao"] == "criado"
    assert resultado["extrato_arquivado"]["data_referencia"] == ref.isoformat()

    with Session(banco_temporario) as s:
        registro = s.exec(select(ExtratoImportado)).one()
        assert registro.data_referencia == ref
        assert registro.arquivo == "extrato_exemplo.xlsx"
        assert registro.total_posicoes == staging_completo["total_posicoes"]
        assert registro.total_valor_mercado == pytest.approx(
            staging_completo["total_valor_mercado"], abs=0.01
        )


async def test_arquivo_guarda_o_que_a_tabela_posicao_perde(banco_temporario, staging_completo,
                                                           extrato_parseado):
    """
    Proventos, movimentações, aluguel e valores em trânsito não têm coluna em Posicao.
    Só sobrevivem se o payload do mês for guardado inteiro.
    """
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes()

    with Session(banco_temporario) as s:
        payload = json.loads(s.exec(select(ExtratoImportado)).one().payload_json)

    # O bruto do parser, não o preview: só ele tem as movimentações.
    for campo in ("proventos", "movimentacoes", "aluguel", "valores_em_transito", "sumario"):
        assert campo in payload, f"campo {campo} nao foi arquivado"

    assert len(payload["proventos"]) == len(extrato_parseado.proventos)
    assert len(payload["movimentacoes"]) == len(extrato_parseado.movimentacoes)
    assert len(payload["posicoes"]) == len(extrato_parseado.posicoes)


async def test_reimportar_o_mesmo_mes_corrige_em_vez_de_duplicar(banco_temporario,
                                                                 extrato_parseado):
    """Reenviar o mesmo XLSX é rotina — não pode virar dois meses nem dois pontos no gráfico."""
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.models.snapshot_mensal import SnapshotMensal
    from app.tools import extrato_staging
    from app.tools.extrato import montar_preview
    from app.tools.gravar import tool_gravar_posicoes

    preview = montar_preview(extrato_parseado, "extrato_exemplo.xlsx")
    bruto = extrato_parseado.to_dict()

    extrato_staging.set_preview(preview, "extrato_exemplo.xlsx", bruto=bruto)
    primeiro = await tool_gravar_posicoes()

    extrato_staging.set_preview(preview, "reenvio.xlsx", bruto=bruto)
    segundo = await tool_gravar_posicoes()

    assert primeiro["extrato_arquivado"]["acao"] == "criado"
    assert segundo["extrato_arquivado"]["acao"] == "atualizado"
    assert segundo["snapshot"]["acao"] == "atualizado"

    with Session(banco_temporario) as s:
        registros = s.exec(select(ExtratoImportado)).all()
        assert len(registros) == 1
        assert registros[0].arquivo == "reenvio.xlsx", "o reenvio corrige a linha existente"
        assert len(s.exec(select(SnapshotMensal)).all()) == 1


async def test_snapshot_usa_a_data_e_o_valor_do_extrato(banco_temporario, staging_completo):
    """
    Buscar preço de hoje para um extrato de meses atrás produziria um total que nunca
    existiu. O número oficial daquela data é o do próprio extrato.
    """
    from datetime import date
    from sqlmodel import Session, select
    from app.models.snapshot_mensal import SnapshotMensal
    from app.tools.gravar import tool_gravar_posicoes

    resultado = await tool_gravar_posicoes()
    ref = date.fromisoformat(staging_completo["data_referencia"])

    assert resultado["snapshot"]["acao"] == "criado"

    with Session(banco_temporario) as s:
        snap = s.exec(select(SnapshotMensal)).one()

    assert snap.data_referencia == ref, "a data e a do extrato, nao date.today()"
    assert snap.valor_total == pytest.approx(staging_completo["total_valor_mercado"], abs=0.01)

    payload = json.loads(snap.payload_json)
    assert payload["origem"] == "extrato_btg_xlsx"
    assert len(payload["posicoes"]) == staging_completo["total_posicoes"]
    assert all(p["source"] == "extrato" for p in payload["posicoes"])


async def test_gravacao_manual_nao_arquiva(banco_temporario):
    """
    Sem extrato em staging não há mês fechado: adicionar uma posição à mão não pode
    inventar um extrato nem um ponto no gráfico.
    """
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.models.snapshot_mensal import SnapshotMensal
    from app.tools.gravar import tool_gravar_posicoes

    resultado = await tool_gravar_posicoes([
        {"ticker": "PETR4", "nome": "PETROBRAS PN", "classe": "ACAO",
         "quantidade": 100, "valor_mercado": 3800.0},
    ])

    assert resultado["total_gravadas"] == 1
    assert "extrato_arquivado" not in resultado
    assert "snapshot" not in resultado

    with Session(banco_temporario) as s:
        assert s.exec(select(ExtratoImportado)).all() == []
        assert s.exec(select(SnapshotMensal)).all() == []


async def test_lote_com_erro_nao_arquiva(banco_temporario, staging_completo):
    """
    Espelha a reconciliação: um lote que falhou não é a carteira completa daquele mês,
    então não pode virar histórico oficial.
    """
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.tools import extrato_staging
    from app.tools.gravar import tool_gravar_posicoes

    quebrado = {**staging_completo, "posicoes": [dict(p) for p in staging_completo["posicoes"]]}
    quebrado["posicoes"][0] = {**quebrado["posicoes"][0], "nome": ""}  # posição sem nome
    extrato_staging.set_preview(quebrado, "quebrado.xlsx", bruto=None)

    resultado = await tool_gravar_posicoes()

    assert "extrato_arquivado" not in resultado
    assert any("sem nome" in a for a in resultado["avisos"])

    with Session(banco_temporario) as s:
        assert s.exec(select(ExtratoImportado)).all() == []


async def test_extrato_retroativo_nao_destroi_a_carteira(banco_temporario, extrato_parseado):
    """
    Ter histórico convida a subir extratos antigos para preenchê-lo. Sem esta guarda, a
    reconciliação leria a foto do mês antigo como "a carteira agora" e desativaria tudo
    o que foi comprado depois — perda silenciosa disparada por um import de rotina.
    """
    from datetime import date, timedelta
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado
    from app.models.posicao import Posicao
    from app.tools import extrato_staging
    from app.tools.extrato import montar_preview
    from app.tools.gravar import tool_gravar_posicoes

    atual = montar_preview(extrato_parseado, "atual.xlsx")
    bruto = extrato_parseado.to_dict()
    extrato_staging.set_preview(atual, "atual.xlsx", bruto=bruto)
    await tool_gravar_posicoes()

    with Session(banco_temporario) as s:
        ativas_antes = {p.nome: p.valor_mercado
                        for p in s.exec(select(Posicao).where(Posicao.ativo == True)).all()}

    # Mês anterior: metade das posições e valores diferentes — a carteira de antes.
    ref_antiga = (date.fromisoformat(atual["data_referencia"]) - timedelta(days=31)).isoformat()
    antigo = {
        **atual,
        "data_referencia": ref_antiga,
        "posicoes": [dict(p) for p in atual["posicoes"][:5]],
        "total_posicoes": 5,
    }
    extrato_staging.set_preview(antigo, "antigo.xlsx", bruto={**bruto, "data_referencia": ref_antiga})

    resultado = await tool_gravar_posicoes()

    assert resultado["modo"] == "somente_historico"
    assert resultado["carteira_alterada"] is False
    assert resultado["total_gravadas"] == 0
    assert resultado["posicoes_desativadas"] == []
    assert any("mexi na carteira" in a for a in resultado["avisos"]), resultado["avisos"]

    # O mês antigo entrou no histórico...
    with Session(banco_temporario) as s:
        assert len(s.exec(select(ExtratoImportado)).all()) == 2
        ativas_depois = {p.nome: p.valor_mercado
                         for p in s.exec(select(Posicao).where(Posicao.ativo == True)).all()}

    # ...e a carteira ficou exatamente como estava.
    assert ativas_depois == ativas_antes


def test_upload_deixa_o_bruto_no_staging():
    """
    O elo frágil: se o endpoint parar de mandar o bruto, o arquivamento continua
    passando (cai no preview) e as movimentacoes somem sem ninguem notar.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.extrato import router
    from app.tools import extrato_staging

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with FIXTURE.open("rb") as fh:
        resp = client.post("/extrato/upload", files={"arquivo": ("extrato_exemplo.xlsx", fh)})
    assert resp.status_code == 200, resp.text

    bruto = extrato_staging.get()["bruto"]
    assert bruto is not None, "o upload precisa guardar o extrato completo"
    assert "movimentacoes" in bruto, "campo que so existe no bruto"


async def test_api_historico_lista_e_detalha(banco_temporario, staging_completo):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.extrato import router
    from app.tools.gravar import tool_gravar_posicoes

    await tool_gravar_posicoes()

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    lista = client.get("/extrato/historico")
    assert lista.status_code == 200, lista.text
    linhas = lista.json()
    assert len(linhas) == 1
    ref = linhas[0]["data_referencia"]
    assert linhas[0]["total_posicoes"] == staging_completo["total_posicoes"]

    detalhe = client.get(f"/extrato/historico/{ref}")
    assert detalhe.status_code == 200, detalhe.text
    corpo = detalhe.json()
    assert corpo["data_referencia"] == ref
    assert "proventos" in corpo["extrato"]
    assert "movimentacoes" in corpo["extrato"]

    assert client.get("/extrato/historico/1999-01-31").status_code == 404
