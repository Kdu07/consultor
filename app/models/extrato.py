from typing import Optional
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field


class ExtratoImportado(SQLModel, table=True):
    """
    Arquivo histórico de um extrato já importado.

    A tabela Posicao guarda só o ESTADO ATUAL da carteira — o upsert de
    gravar_posicoes sobrescreve quantidade e valor a cada import, e proventos,
    movimentações, aluguel e valores em trânsito nunca chegavam ao banco. Aqui fica
    a fotografia completa do que o extrato daquele mês dizia, do jeito que o parser
    leu, para que a série histórica (renda passiva, aportes, evolução) possa ser
    reconstruída depois.

    `data_referencia` é única: reimportar o mesmo mês corrige o registro em vez de
    duplicá-lo. O XLSX original continua não sendo guardado (contém nome, CPF e
    conta) — o payload tem apenas dados já estruturados pelo parser, que não extrai
    nenhum identificador pessoal.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    data_referencia: date = Field(index=True, unique=True)
    arquivo: Optional[str] = Field(default=None)  # nome do XLSX enviado, só para rastreio

    # Agregados desnormalizados — listar o histórico sem abrir o JSON de cada linha.
    total_posicoes: int = Field(default=0)
    total_valor_mercado: float = Field(default=0.0)
    proventos_total: float = Field(default=0.0)
    proventos_quantidade: int = Field(default=0)

    # Extrato completo do parser (ExtratoParsed.to_dict): posições, sumário,
    # proventos, movimentações, aluguel, valores em trânsito, checagem e linhas
    # ignoradas. É o que permite reprocessar sem ter o arquivo de novo.
    payload_json: str

    importado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    atualizado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
