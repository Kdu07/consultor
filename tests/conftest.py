"""
Rede de segurança: nenhum teste toca o banco real (data/carteira.db).

O engine do app nasce no import de app.database, com o DATABASE_URL daquele momento. Este
arquivo é carregado antes de qualquer módulo de teste importar o app, então o engine "de
fábrica" já aponta para um SQLite descartável, sem tabelas. As fixtures de cada arquivo de
teste continuam trocando o engine por um banco próprio, com schema — isto é só a rede
embaixo delas: um teste que esqueça de trocar o engine falha, em vez de escrever na
carteira de verdade.
"""
import os
import tempfile
from pathlib import Path

import pytest

_DIRETORIO = Path(tempfile.mkdtemp(prefix="consultor-testes-"))
_URL_DESCARTAVEL = f"sqlite:///{(_DIRETORIO / 'rede.db').as_posix()}"
os.environ["DATABASE_URL"] = _URL_DESCARTAVEL


@pytest.fixture(autouse=True)
def _banco_padrao_descartavel(monkeypatch):
    """Reaplica o DATABASE_URL descartável a cada teste — há teste que mexe em os.environ."""
    monkeypatch.setenv("DATABASE_URL", _URL_DESCARTAVEL)
    yield


@pytest.fixture(autouse=True)
def _bcb_sem_rede(monkeypatch):
    """
    Nenhum teste vai ao BCB. Por padrão a SGS "responde" que ainda não há dados; quem testa
    benchmarks troca o cliente por um transporte próprio.
    """
    import httpx
    from app.tools import benchmarks

    def _sem_dados(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"erro": {"statusCode": 404, "detail": "Value(s) not found"}})

    benchmarks.limpar_estado()
    monkeypatch.setattr(
        benchmarks, "_novo_cliente",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_sem_dados)),
    )
    yield
    benchmarks.limpar_estado()
