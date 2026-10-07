"""
Lote de extratos, exclusão de mês, lançamentos e regras (docs/PLANO_HISTORICO.md, Bloco 5).

A garantia central: confirmar o lote NUNCA toca na carteira. Ele só arquiva meses que não a
mexem — e reavalia isso no clique, porque entre o envio e a confirmação outro mês pode ter
sido importado pelo chat.
"""
from datetime import date, datetime, timezone

import pytest

from tests.gerador_extrato import (
    CAIXA_INI_FIXTURE,
    RENTABILIDADE_PCT_FIXTURE,
    TOTAL_BRUTO_FIM_FIXTURE,
)
from tests.planilhas import abrir_fixture, bytes_fixture, definir_periodo, para_bytes


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")
    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    import app.models  # noqa: F401
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


# ---------------------------------------------------------------------------
# Arquivos e estados de carteira
# ---------------------------------------------------------------------------

def _xlsx(inicio: date | None = None, fim: date | None = None, bbas3_mais: float = 0.0) -> bytes:
    wb = abrir_fixture()
    if inicio and fim:
        definir_periodo(wb, inicio, fim)
    if bbas3_mais:
        for row in wb["Renda Variavel"].iter_rows():
            if row[1].value == "BBAS3":
                row[6].value = float(row[6].value) + bbas3_mais   # Saldo Bruto R$
    return para_bytes(wb)


JULHO = bytes_fixture()
JUNHO = _xlsx(date(2026, 6, 1), date(2026, 6, 30))
SETEMBRO = _xlsx(date(2026, 9, 1), date(2026, 9, 30))
AGOSTO_PARCIAL = _xlsx(date(2026, 8, 1), date(2026, 8, 10))


def _enviar(cliente, arquivos: list[tuple[str, bytes]]) -> dict:
    files = [("arquivos", (nome, conteudo)) for nome, conteudo in arquivos]
    resp = cliente.post("/extrato/lote", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _carteira_em_10_de_agosto(engine):
    """Produção em 10/2026: posições do extrato com as_of 2026-08-10, nada arquivado."""
    from sqlmodel import Session
    from app.models.posicao import ClasseAtivo, Posicao
    from app.seeds import _seed_referencia_carteira
    from app.tools.btg_xlsx_parser import parse_btg_xlsx

    with Session(engine) as s:
        for p in parse_btg_xlsx(JULHO).posicoes:
            s.add(Posicao(
                ticker=p.ticker, nome=p.nome, classe=ClasseAtivo(p.classe), quantidade=p.quantidade,
                valor_mercado=p.valor_mercado, chave_externa=p.chave_externa, source="extrato",
                as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ))
        s.commit()
        _seed_referencia_carteira(s)
        s.commit()


async def _importar_pelo_chat(conteudo: bytes, nome: str = "x.xlsx"):
    from app.tools import extrato_staging
    from app.tools.btg_xlsx_parser import parse_btg_xlsx
    from app.tools.extrato import montar_preview
    from app.tools.gravar import tool_gravar_posicoes

    extrato = parse_btg_xlsx(conteudo)
    extrato_staging.set_preview(montar_preview(extrato, nome), nome, bruto=extrato.to_dict())
    return await tool_gravar_posicoes()


def _carteira(engine) -> dict:
    from sqlmodel import Session, select
    from app.models.posicao import Posicao

    with Session(engine) as s:
        return {p.chave_externa: (p.quantidade, p.valor_mercado, p.ativo, p.atualizado_em)
                for p in s.exec(select(Posicao)).all()}


def _arquivados(engine) -> list[str]:
    from sqlmodel import Session, select
    from app.models.extrato import ExtratoImportado

    with Session(engine) as s:
        return sorted(e.data_referencia.isoformat() for e in s.exec(select(ExtratoImportado)).all())


# ---------------------------------------------------------------------------
# Lote
# ---------------------------------------------------------------------------

def test_matriz_de_status_no_cenario_de_producao(banco, cliente):
    _carteira_em_10_de_agosto(banco)
    lote = _enviar(cliente, [
        ("001234567.xlsx", JULHO),
        ("junho.xlsx", JUNHO),
        ("junho-de-novo.xlsx", JUNHO),
        ("setembro.xlsx", SETEMBRO),
        ("agosto-parcial.xlsx", AGOSTO_PARCIAL),
        ("notas.txt", b"qualquer coisa"),
        ("quebrado.xlsx", b"isto nao e xlsx"),
    ])
    assert lote["data_corte"] == "2026-08-10"
    status = [(i["data_referencia"], i["status"]) for i in lote["itens"]]
    assert status == [
        ("2026-07-31", "novo"),
        ("2026-06-30", "novo"),
        ("2026-06-30", "duplicado_no_lote"),
        ("2026-09-30", "mais_novo_que_carteira"),
        ("2026-08-10", "periodo_nao_mensal"),
        (None, "erro"),
        (None, "erro"),
    ]
    julho = lote["itens"][0]
    assert julho["arquivo"] == "***.xlsx", "o nome do arquivo do BTG é o número da conta"
    assert julho["selecionavel"] and julho["selecionado_padrao"]
    assert julho["lancamentos"] == 5 and julho["checagem_conta_ok"] is True
    assert julho["rentabilidade_pct"] == pytest.approx(RENTABILIDADE_PCT_FIXTURE, abs=1e-3)
    assert not lote["itens"][3]["selecionavel"]
    assert all(not k.startswith("_") for i in lote["itens"] for k in i)


def test_confirmar_arquiva_e_nao_toca_na_carteira(banco, cliente):
    _carteira_em_10_de_agosto(banco)
    antes = _carteira(banco)
    lote = _enviar(cliente, [("julho.xlsx", JULHO), ("junho.xlsx", JUNHO), ("setembro.xlsx", SETEMBRO)])

    resp = cliente.post(f"/extrato/lote/{lote['id']}/confirmar",
                        json={"datas": ["2026-07-31", "2026-06-30", "2026-09-30"]})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert [a["data_referencia"] for a in corpo["arquivados"]] == ["2026-07-31", "2026-06-30"]
    assert [(r["data_referencia"], r["motivo"]) for r in corpo["recusados"]] == [
        ("2026-09-30", "mais_novo_que_carteira")
    ]
    assert corpo["carteira_alterada"] is False

    assert _carteira(banco) == antes, "o lote não pode mexer em nenhuma posição"
    assert _arquivados(banco) == ["2026-06-30", "2026-07-31"]

    # o lote é de uso único
    assert cliente.post(f"/extrato/lote/{lote['id']}/confirmar", json={"datas": []}).status_code == 404


async def test_reenvio_do_mes_atual_e_divergencia(banco, cliente):
    await _importar_pelo_chat(JULHO)   # carteira = julho; julho arquivado como v2

    lote = _enviar(cliente, [("julho.xlsx", JULHO), ("julho-mexido.xlsx", _xlsx(bbas3_mais=100.0))])
    reenvio, mexido = lote["itens"]
    assert reenvio["status"] == "reenvio_do_atual"
    assert reenvio["selecionavel"] is True
    assert reenvio["selecionado_padrao"] is False, "já arquivado com razão: não precisa"
    # Mesmo mês duas vezes no lote: o segundo é duplicado, antes de qualquer comparação.
    assert mexido["status"] == "duplicado_no_lote"

    lote = _enviar(cliente, [("julho-mexido.xlsx", _xlsx(bbas3_mais=100.0))])
    assert lote["itens"][0]["status"] == "diverge_da_carteira"
    assert lote["itens"][0]["selecionavel"] is False


async def test_confirmacao_reavalia_contra_o_banco_de_agora(banco, cliente):
    await _importar_pelo_chat(JULHO)
    lote = _enviar(cliente, [("julho.xlsx", JULHO)])
    assert lote["itens"][0]["status"] == "reenvio_do_atual"

    # Entre o envio e o clique, a carteira mudou pelo chat.
    await _importar_pelo_chat(_xlsx(bbas3_mais=100.0))

    corpo = cliente.post(f"/extrato/lote/{lote['id']}/confirmar", json={"datas": ["2026-07-31"]}).json()
    assert corpo["arquivados"] == []
    assert corpo["recusados"][0]["motivo"] == "diverge_da_carteira"


def test_mes_arquivado_sem_razao_e_marcado_para_completar(banco, cliente):
    import json
    from sqlmodel import Session
    from app.models.extrato import ExtratoImportado
    from app.tools.btg_xlsx_parser import parse_btg_xlsx

    _carteira_em_10_de_agosto(banco)
    v1 = parse_btg_xlsx(JUNHO).to_dict()
    for chave in ("versao_parser", "lancamentos_conta", "lotes_rf", "saldo_inicial_conta"):
        v1.pop(chave)
    with Session(banco) as s:
        s.add(ExtratoImportado(data_referencia=date(2026, 6, 30), payload_json=json.dumps(v1)))
        s.commit()

    item = _enviar(cliente, [("junho.xlsx", JUNHO)])["itens"][0]
    assert item["status"] == "substitui"
    assert item["completa_lancamentos"] is True
    assert item["selecionado_padrao"] is True


def test_lote_grande_demais_e_descartar(banco, cliente):
    from app.tools.extrato_lote import MAX_ARQUIVOS

    files = [("arquivos", (f"{i}.xlsx", b"x")) for i in range(MAX_ARQUIVOS + 1)]
    assert cliente.post("/extrato/lote", files=files).status_code == 400

    lote = _enviar(cliente, [("julho.xlsx", JULHO)])
    assert cliente.delete(f"/extrato/lote/{lote['id']}").status_code == 204
    assert cliente.post(f"/extrato/lote/{lote['id']}/confirmar", json={"datas": []}).status_code == 404


# ---------------------------------------------------------------------------
# Histórico: lista enriquecida, lançamentos, exclusão
# ---------------------------------------------------------------------------

async def test_historico_enriquecido_e_lancamentos_do_mes(banco, cliente):
    await _importar_pelo_chat(JULHO)

    linha = cliente.get("/extrato/historico").json()[0]
    assert linha["mes"] == "2026-07"
    assert linha["patrimonio"] == pytest.approx(TOTAL_BRUTO_FIM_FIXTURE)
    assert linha["status"] == "ok"
    assert linha["tem_lancamentos"] is True and linha["lancamentos"] == 5
    assert linha["protegido"] is True, "é o mês que a carteira reflete"

    corpo = cliente.get("/extrato/historico/2026-07-31/lancamentos").json()
    assert corpo["tem_lancamentos"] is True
    assert corpo["saldo_inicial"] == pytest.approx(CAIXA_INI_FIXTURE)
    assert [l["tipo"] for l in corpo["lancamentos"]] == ["PROVENTO"] * 4 + ["RENDIMENTO_CAIXA"]
    assert corpo["lancamentos"][0]["rotulo"] == "Provento"
    assert corpo["lancamentos"][0]["padrao_sugerido"] == "juros s/ capital"

    assert cliente.get("/extrato/historico/1999-01-31/lancamentos").status_code == 404


async def test_excluir_mes(banco, cliente):
    from sqlmodel import Session, select
    from app.models.regra_lancamento import RegraLancamento

    await _importar_pelo_chat(JULHO)
    lote = _enviar(cliente, [("junho.xlsx", JUNHO)])
    cliente.post(f"/extrato/lote/{lote['id']}/confirmar", json={"datas": ["2026-06-30"]})
    # uma regra de linha presa a junho
    assert cliente.post("/extrato/regras", json={
        "tipo": "APORTE", "escopo": "linha", "data_referencia": "2026-06-30", "seq": 0,
    }).status_code == 201

    assert cliente.delete("/extrato/historico/2026-07-31").status_code == 409
    assert cliente.delete("/extrato/historico/2026-06-30").status_code == 204
    assert cliente.delete("/extrato/historico/2026-06-30").status_code == 404
    assert _arquivados(banco) == ["2026-07-31"]
    with Session(banco) as s:
        assert s.exec(select(RegraLancamento)).all() == [], "a regra da linha foi junto com o mês"


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------

async def test_regras_pela_api(banco, cliente):
    await _importar_pelo_chat(JULHO)

    resp = cliente.post("/extrato/regras", json={"tipo": "OUTRO_INTERNO", "padrao": "rendimentos"})
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["nova"] is True
    assert corpo["afetados"] == {"meses": 1, "lancamentos": 3}
    regra_id = corpo["regra"]["id"]

    tipos = [l["tipo"] for l in cliente.get("/extrato/historico/2026-07-31/lancamentos").json()["lancamentos"]]
    assert tipos.count("OUTRO_INTERNO") == 3

    linha = cliente.post("/extrato/regras", json={
        "tipo": "APORTE", "escopo": "linha", "data_referencia": "2026-07-31", "seq": 4,
    }).json()
    lanc = cliente.get("/extrato/historico/2026-07-31/lancamentos").json()["lancamentos"][4]
    assert (lanc["tipo"], lanc["origem"], lanc["regra_id"]) == ("APORTE", "linha", linha["regra"]["id"])

    assert len(cliente.get("/extrato/regras").json()) == 2
    assert cliente.post("/extrato/regras", json={"tipo": "INVENTADO", "padrao": "x"}).status_code == 400
    assert cliente.post("/extrato/regras", json={
        "tipo": "APORTE", "escopo": "linha", "data_referencia": "2026-07-31", "seq": 99,
    }).status_code == 404
    assert cliente.delete(f"/extrato/regras/{regra_id}").status_code == 204
    assert cliente.delete(f"/extrato/regras/{regra_id}").status_code == 404
