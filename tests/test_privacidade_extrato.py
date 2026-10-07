"""
Privacidade do histórico (docs/PLANO_HISTORICO.md): o extrato traz nome, CPF e conta — do
dono e de quem mandou um PIX. Nada disso pode chegar ao banco nem aos logs.

Ponta a ponta: um extrato sintético com transferências "sujas" passa pelo lote, é
confirmado, e o payload gravado é varrido campo de texto por campo de texto. Só os campos
de texto: números (ex.: um saldo 43115.00) dariam falso positivo nas regex de dígitos.
"""
import json
import logging
import re
from datetime import date, datetime

import pytest

from tests.planilhas import abrir_fixture, adicionar_lancamentos, definir_periodo, para_bytes

NOME = "FULANO DE TAL DA SILVA"
PADROES = {
    "cpf": re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
    "cnpj": re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"),
    "conta com dígito": re.compile(r"(?<!\d)\d{3,}-[\dXx](?![\dA-Za-z])"),
    "sequência longa": re.compile(r"(?<!\d)\d{5,}(?!\d)"),
}


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/teste.db")
    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as database
    import app.models  # noqa: F401
    from sqlmodel import SQLModel

    engine = database._make_engine()
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    get_settings.cache_clear()


def _textos(valor, caminho="") -> list[tuple[str, str]]:
    """Todas as strings do payload (chaves e valores), com o caminho até elas."""
    if isinstance(valor, dict):
        out = []
        for k, v in valor.items():
            out.append((f"{caminho}.{k}#chave", str(k)))
            out.extend(_textos(v, f"{caminho}.{k}"))
        return out
    if isinstance(valor, list):
        return [t for i, v in enumerate(valor) for t in _textos(v, f"{caminho}[{i}]")]
    if isinstance(valor, str):
        return [(caminho, valor)]
    return []


def _extrato_sujo() -> bytes:
    wb = abrir_fixture()
    definir_periodo(wb, date(2026, 6, 1), date(2026, 6, 30))
    adicionar_lancamentos(wb, [
        (date(2026, 6, 10), f"PIX RECEBIDO - {NOME} CPF 123.456.789-00", 2_000.00),
        (date(2026, 6, 12), f"TED ENVIADA BCO 341 AG 0001 CC 12345-6 {NOME}", -500.00),
        (date(2026, 6, 15), "TRANSFERENCIA ENTRE CONTAS 00012345678", 300.00),
        (date(2026, 6, 18), "DEVOLUCAO CNPJ 12.345.678/0001-90 REF 987654321", 10.00),
    ])
    return para_bytes(wb)


def test_nada_pessoal_chega_ao_banco_nem_ao_log(banco, caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select
    from app.api.extrato_lote import router
    from app.models.extrato import ExtratoImportado
    from app.models.posicao import ClasseAtivo, Posicao
    from app.tools import extrato_lote

    # Carteira em julho: junho entra como histórico pelo lote.
    with Session(banco) as s:
        s.add(Posicao(nome="X", ticker="BBAS3", classe=ClasseAtivo.ACAO, chave_externa="B3:BBAS3",
                      quantidade=1, valor_mercado=1.0, source="extrato",
                      as_of=datetime(2026, 7, 31)))
        s.commit()

    app = FastAPI()
    app.include_router(router)
    cliente = TestClient(app)
    caplog.set_level(logging.INFO)
    try:
        lote = cliente.post("/extrato/lote", files=[("arquivos", ("001234567.xlsx", _extrato_sujo()))]).json()
        item = lote["itens"][0]
        assert item["status"] == "novo", item
        assert item["arquivo"] == "***.xlsx"
        resp = cliente.post(f"/extrato/lote/{lote['id']}/confirmar", json={"datas": [item["data_referencia"]]})
        assert resp.json()["arquivados"], resp.text
    finally:
        extrato_lote.descartar()

    with Session(banco) as s:
        registro = s.exec(select(ExtratoImportado)).one()
    payload = json.loads(registro.payload_json)
    assert registro.arquivo == "***.xlsx"

    textos = _textos(payload)
    for caminho, texto in textos:
        assert "FULANO" not in texto.upper(), f"nome em {caminho}: {texto!r}"
        for nome, padrao in PADROES.items():
            assert not padrao.search(texto), f"{nome} em {caminho}: {texto!r}"

    descricoes = {l["descricao"] for l in payload["lancamentos_conta"]}
    assert {"PIX RECEBIDO", "TED ENVIADA", "TRANSFERENCIA ENTRE CONTAS RECEBIDO"} <= descricoes

    log = caplog.text
    assert "FULANO" not in log
    assert "001234567" not in log
    assert not PADROES["cpf"].search(log)
    assert "PIX RECEBIDO" not in log, "descrição de lançamento não vai para log"
