"""
Autoconsistência do gerador de extratos sintéticos (tests/gerador_extrato.py).

Duas camadas:
  - invariantes no nível do WORKBOOK (células somadas na mão) — valem com qualquer parser;
  - o parser lê fixture_padrao() e produz posições/checagens coerentes, e cada knob da
    EspecExtrato produz exatamente o defeito pedido, com a severidade esperada.

Nenhum número aqui vem de extrato real: tudo deriva das constantes do gerador.
"""
from datetime import date

import pytest

from app.tools.btg_xlsx_parser import parse_btg_xlsx
from tests.gerador_extrato import (
    ALUGUEL_RESULTADO_FIXTURE,
    CAIXA_FIM_FIXTURE,
    CAIXA_INI_FIXTURE,
    CREDITOS_FIXTURE,
    DATA_ANTERIOR_FIXTURE,
    DATA_REFERENCIA_FIXTURE,
    EspecExtrato,
    LANCAMENTOS_FIXTURE,
    LOTES_RF_FIXTURE,
    NTNB_CUSTO_TOTAL_FIXTURE,
    NTNB_PRECO_MEDIO_FIXTURE,
    PROVENTOS_FIXTURE,
    PROVENTOS_LIQUIDOS_FIXTURE,
    RF_BRUTO_FIXTURE,
    RV_POSICOES_FIXTURE,
    RV_SUMARIO_FIM_FIXTURE,
    TOTAL_BRUTO_FIM_FIXTURE,
    TOTAL_BRUTO_INI_FIXTURE,
    TOTAL_POSICOES_FIXTURE,
    TOTAL_POSICOES_VALOR_FIXTURE,
    TRANSITO_FIXTURE,
    construir,
    fixture_padrao,
    gerar,
)


def _sumario(wb) -> dict[str, list[float]]:
    """{mercado: [bruto_ini, liq_ini, bruto_fim, liq_fim]} lido das células."""
    ws = wb["Sumario"]
    cab = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == "Mercados")
    out: dict[str, list] = {}
    for r in range(cab + 1, ws.max_row + 1):
        nome = ws.cell(r, 2).value
        if nome:
            out[str(nome)] = [ws.cell(r, c).value for c in range(3, 7)]
    return out


# ---------------------------------------------------------------------------
# Invariantes no nível do workbook
# ---------------------------------------------------------------------------

def test_sumario_soma_nas_quatro_colunas():
    linhas = _sumario(fixture_padrao())
    total = linhas.pop("Total")
    for i in range(4):
        soma = round(sum(v[i] for v in linhas.values() if isinstance(v[i], (int, float))), 2)
        assert soma == pytest.approx(total[i], abs=0.005), f"coluna {i} não soma no Total"


def test_rv_do_sumario_e_blocos_mais_aluguel():
    """A armadilha real do BTG, reproduzida de propósito: Sumário RV = posições + aluguel."""
    wb = fixture_padrao()
    ws = wb["Renda Variavel"]
    totais_blocos = 0.0
    resultado_aluguel = None
    for r in range(1, ws.max_row + 1):
        rotulo = ws.cell(r, 2).value
        if not isinstance(rotulo, str):
            continue
        if rotulo.startswith("Total em Aluguel"):
            resultado_aluguel = ws.cell(r, 12).value
        elif rotulo.startswith("Total em"):
            valor = next(ws.cell(r, c).value for c in range(3, 12) if ws.cell(r, c).value is not None)
            totais_blocos += valor
    assert round(totais_blocos, 2) == pytest.approx(RV_POSICOES_FIXTURE)
    assert resultado_aluguel == pytest.approx(ALUGUEL_RESULTADO_FIXTURE)
    assert resultado_aluguel > 1.00, "o aluguel tem de estourar uma tolerância de R$ 1,00"
    linhas = _sumario(wb)
    assert linhas["Renda Variável"][2] == pytest.approx(
        round(totais_blocos + resultado_aluguel, 2)
    )
    assert linhas["Renda Variável"][2] == pytest.approx(RV_SUMARIO_FIM_FIXTURE)


def test_razao_fecha_no_workbook():
    from datetime import datetime

    ws = fixture_padrao()["Conta Corrente"]
    saldo = None
    for r in range(1, ws.max_row + 1):
        desc = ws.cell(r, 3).value
        valor, saldo_cel = ws.cell(r, 4).value, ws.cell(r, 5).value
        if not isinstance(ws.cell(r, 2).value, datetime):
            continue   # só as linhas do razão têm data na coluna 2
        if desc == "Saldo Anterior":
            saldo = saldo_cel
            assert saldo == pytest.approx(CAIXA_INI_FIXTURE)
        elif saldo is not None and isinstance(valor, (int, float)):
            saldo = round(saldo + valor, 2)
            assert saldo_cel == pytest.approx(saldo), f"razão quebrou na linha {r}"
    assert saldo == pytest.approx(CAIXA_FIM_FIXTURE)
    assert _sumario(fixture_padrao())["Conta Corrente"][2] == pytest.approx(CAIXA_FIM_FIXTURE)


def test_desalinhar_sumario_desloca_so_o_mercado_pedido():
    delta = 2.00
    linhas = _sumario(construir(EspecExtrato(desalinhar_sumario={"Renda Fixa": delta})))
    assert linhas["Renda Fixa"][2] == pytest.approx(round(RF_BRUTO_FIXTURE + delta, 2))
    # o Total acompanha: o Sumário continua internamente consistente (V1 ok, V3 acusa)
    total = linhas.pop("Total")
    soma = round(sum(v[2] for v in linhas.values() if isinstance(v[2], (int, float))), 2)
    assert soma == pytest.approx(total[2], abs=0.005)


def test_desalinhar_total_quebra_so_a_linha_total():
    delta = 0.50
    linhas = _sumario(construir(EspecExtrato(desalinhar_total=delta)))
    total = linhas.pop("Total")
    soma = round(sum(v[2] for v in linhas.values() if isinstance(v[2], (int, float))), 2)
    assert round(total[2] - soma, 2) == pytest.approx(delta)


def test_decorar_tickers_poe_asterisco_em_tudo():
    wb = construir(EspecExtrato(decorar_tickers=True))
    rv = wb["Renda Variavel"]
    codigos = [rv.cell(r, 2).value for r in range(1, rv.max_row + 1)
               if isinstance(rv.cell(r, 2).value, str) and rv.cell(r, 2).value.endswith("*")]
    assert "BBAS3*" in codigos and "TAEE11*" in codigos
    rf = wb["Renda Fixa"]
    ativos = {rf.cell(r, 3).value for r in range(1, rf.max_row + 1)}
    assert "LFT* " in ativos, "na RF o asterisco vem com espaço no fim, como no BTG"
    linhas = _sumario(wb)
    assert "Renda Variável*" in linhas and "Renda Fixa*" in linhas
    nota = [rv.cell(r, 2).value for r in range(1, rv.max_row + 1)
            if isinstance(rv.cell(r, 2).value, str) and rv.cell(r, 2).value.startswith("* Seção")]
    assert nota, "extrato decorado leva a nota de rodapé do BTG"


def test_abas_opcionais_fundos_e_cripto():
    wb = construir(EspecExtrato(com_fundos=True, com_cripto=True))
    assert [ws.title for ws in wb.worksheets] == [
        "Capa", "Sumario", "Fundos", "Renda Fixa", "Renda Variavel", "CriptoAtivos",
        "Conta Corrente", "Valores em Trânsito", "Fale Conosco",
    ]
    linhas = _sumario(wb)
    fundos = wb["Fundos"]
    textos = [fundos.cell(r, 2).value for r in range(1, fundos.max_row + 1)
              if isinstance(fundos.cell(r, 2).value, str)]
    assert any(t.startswith("Posição > Portfólio de fundos") for t in textos)
    assert any("Classe CNPJ:" in t for t in textos), "registro de fundo em duas linhas"
    assert any(t.startswith("Movimentação > ") for t in textos)
    assert any(t == "Total em fundos" for t in textos)
    # Sumário de fundos = totais da aba (bruto na coluna 6, líquido na 9)
    r_total = next(r for r in range(1, fundos.max_row + 1)
                   if fundos.cell(r, 2).value == "Total em fundos")
    assert linhas["Fundos de Investimento"][2] == pytest.approx(fundos.cell(r_total, 6).value)
    assert linhas["Fundos de Investimento"][3] == pytest.approx(fundos.cell(r_total, 9).value)

    cripto = wb["CriptoAtivos"]
    cab = next(r for r in range(1, cripto.max_row + 1) if cripto.cell(r, 2).value == "Ativo")
    assert cripto.cell(cab, 5).value == "Valor Liquido R$", "sem acento, como no extrato real"
    r_xbt = cab + 1
    assert cripto.cell(r_xbt, 2).value == "XBT BITCOIN (XBT)"
    qtde, preco = cripto.cell(r_xbt, 3).value, cripto.cell(r_xbt, 4).value
    assert cripto.cell(r_xbt, 8).value == pytest.approx(round(qtde * preco, 2))
    assert linhas["CriptoAtivos"][2] == pytest.approx(cripto.cell(r_xbt, 8).value)


def test_cripto_so_movimentacao_zera_o_sumario():
    wb = construir(EspecExtrato(com_cripto=True, cripto_so_movimentacao=True))
    textos = [wb["CriptoAtivos"].cell(r, 2).value for r in range(1, wb["CriptoAtivos"].max_row + 1)
              if isinstance(wb["CriptoAtivos"].cell(r, 2).value, str)]
    assert not any(t.startswith("Posição >") for t in textos)
    assert any(t.startswith("Movimentação > Portfólio de CriptoAtivos") for t in textos)
    assert _sumario(wb)["CriptoAtivos"][2] == "-"


def test_sumario_extra_poe_mercado_sem_aba():
    linhas = _sumario(construir(EspecExtrato(sumario_extra={"Mercado Futuro": 1234.56})))
    assert linhas["Mercado Futuro"][2] == pytest.approx(1234.56)
    total = linhas.pop("Total")
    soma = round(sum(v[2] for v in linhas.values() if isinstance(v[2], (int, float))), 2)
    assert soma == pytest.approx(total[2], abs=0.005)


# ---------------------------------------------------------------------------
# O parser lê a fixture padrão
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def extrato():
    return parse_btg_xlsx(gerar())


def test_parser_le_a_fixture_padrao(extrato):
    assert extrato.data_referencia == DATA_REFERENCIA_FIXTURE
    por_classe: dict[str, int] = {}
    for p in extrato.posicoes:
        por_classe[p.classe] = por_classe.get(p.classe, 0) + 1
    assert por_classe == {"ACAO": 5, "ETF": 1, "FII": 3, "TESOURO": 5, "CAIXA": 1}
    assert len(extrato.posicoes) == TOTAL_POSICOES_FIXTURE
    assert not extrato.linhas_ignoradas
    assert len(extrato.lotes_rf) == LOTES_RF_FIXTURE
    assert len(extrato.lancamentos_conta) == LANCAMENTOS_FIXTURE
    assert len(extrato.proventos) == PROVENTOS_FIXTURE
    assert extrato.sumario["atual"]["total"]["bruto"] == pytest.approx(TOTAL_BRUTO_FIM_FIXTURE)
    assert extrato.sumario["anterior"]["data"] == DATA_ANTERIOR_FIXTURE
    assert extrato.sumario["anterior"]["total"]["bruto"] == pytest.approx(TOTAL_BRUTO_INI_FIXTURE)


def test_checagens_fecham_na_fixtura_padrao(extrato):
    """Contrato FINAL do parser: o aluguel é descontado do Sumário de RV, então a
    checagem fecha mesmo com resultado de aluguel acima de R$ 1,00."""
    checagem = extrato.checagem
    assert checagem["ok"] is True, checagem.get("aviso")
    assert checagem["total_parseado"] == pytest.approx(TOTAL_POSICOES_VALOR_FIXTURE)
    assert checagem["valores_em_transito_excluidos"] == pytest.approx(TRANSITO_FIXTURE)

    conta = checagem["conta_corrente"]
    assert conta["ok"] is True, conta
    assert conta["diferenca"] == pytest.approx(0.0)
    assert conta["creditos"] == pytest.approx(CREDITOS_FIXTURE)
    assert conta["vs_caixa"] == pytest.approx(0.0)
    assert conta["vs_sumario_anterior"] == pytest.approx(0.0)
    assert checagem["movimentacao_rv"]["ok"] is True


def test_custo_do_tesouro_vem_dos_lotes(extrato):
    ipca = next(p for p in extrato.posicoes if p.ticker == "Tesouro IPCA+ 2029")
    assert ipca.preco_medio == pytest.approx(NTNB_PRECO_MEDIO_FIXTURE, abs=0.05)
    assert ipca.custo_total == pytest.approx(NTNB_CUSTO_TOTAL_FIXTURE)
    total_liquido = sum(p["valor_liquido"] for p in extrato.proventos)
    assert total_liquido == pytest.approx(PROVENTOS_LIQUIDOS_FIXTURE)


# ---------------------------------------------------------------------------
# Knobs de defeito, vistos pelo parser
# ---------------------------------------------------------------------------

def test_descontinuidade_cc_derruba_so_o_razao():
    """O salto real de R$ 0,14 do BTG: o razão não fecha por exatamente esse valor."""
    extrato = parse_btg_xlsx(gerar(EspecExtrato(descontinuidade_cc=0.14)))
    conta = extrato.checagem["conta_corrente"]
    assert conta["ok"] is False
    assert conta["diferenca"] == pytest.approx(-0.14)
    assert conta["vs_caixa"] == pytest.approx(0.0), "a posição da conta segue o saldo saltado"
    assert conta["vs_sumario_anterior"] == pytest.approx(0.0)


def test_saldo_anterior_fora_do_sumario():
    """O desencontro real de centavos do BTG: Saldo Anterior ≠ Sumário do mês anterior."""
    extrato = parse_btg_xlsx(gerar(EspecExtrato(saldo_anterior_delta=0.05)))
    conta = extrato.checagem["conta_corrente"]
    assert conta["diferenca"] == pytest.approx(0.0), "o razão em si continua fechando"
    assert conta["vs_sumario_anterior"] == pytest.approx(0.05)
    assert conta["vs_caixa"] == pytest.approx(0.0)


def test_desalinhamento_grande_vira_erro_de_checagem():
    extrato = parse_btg_xlsx(gerar(EspecExtrato(desalinhar_sumario={"Renda Fixa": 2.00})))
    rf = next(c for c in extrato.checagem["por_mercado"] if c["mercado"] == "Renda Fixa")
    assert rf["diferenca"] == pytest.approx(-2.00)
    assert extrato.checagem["ok"] is False


def test_lancamentos_extras_mantem_o_extrato_coerente():
    """PIX/TED fictícios entram no razão e TODOS os totais acompanham por construção."""
    spec = EspecExtrato(lancamentos_extras=[
        (date(2026, 7, 10), "PIX RECEBIDO - FULANO DE TAL CPF 000.000.000-00", 2000.00),
        (date(2026, 7, 20), "TED ENVIADA BCO 000 AG 0000 CC 00000-0 FULANO DE TAL", -500.00),
    ])
    extrato = parse_btg_xlsx(gerar(spec))
    conta = extrato.checagem["conta_corrente"]
    assert conta["ok"] is True, conta
    assert conta["diferenca"] == pytest.approx(0.0)
    caixa = next(p for p in extrato.posicoes if p.classe == "CAIXA")
    assert caixa.valor_mercado == pytest.approx(round(CAIXA_FIM_FIXTURE + 1500.00, 2))
    descricoes = {l["descricao"] for l in extrato.lancamentos_conta}
    assert "PIX RECEBIDO" in descricoes and "TED ENVIADA" in descricoes
    assert not any("FULANO" in d for d in descricoes), "o parser sanitiza o nome fictício"


def test_periodo_bimestral_e_parcial():
    bimestral = parse_btg_xlsx(gerar(EspecExtrato(inicio=date(2026, 8, 1), fim=date(2026, 9, 30))))
    assert bimestral.data_referencia == "2026-09-30"
    assert bimestral.sumario["meta"]["periodo_inicio"] == "2026-08-01"
    assert bimestral.sumario["anterior"]["data"] == "2026-07-31"

    parcial = parse_btg_xlsx(gerar(EspecExtrato(inicio=date(2026, 8, 1), fim=date(2026, 8, 10))))
    assert parcial.data_referencia == "2026-08-10"
    assert parcial.checagem["conta_corrente"]["ok"] is True, "o razão fecha mesmo em período parcial"


# ---------------------------------------------------------------------------
# Os helpers de tests/planilhas.py continuam valendo sobre o workbook gerado
# ---------------------------------------------------------------------------

def test_helpers_de_planilhas_continuam_coerentes():
    from tests.planilhas import abrir_fixture, adicionar_lancamentos, definir_periodo, para_bytes

    wb = abrir_fixture()
    definir_periodo(wb, date(2026, 6, 1), date(2026, 6, 30))
    novo_saldo = adicionar_lancamentos(wb, [(date(2026, 6, 10), "PIX RECEBIDO", 1000.00)])
    extrato = parse_btg_xlsx(para_bytes(wb))
    assert extrato.data_referencia == "2026-06-30"
    conta = extrato.checagem["conta_corrente"]
    assert conta["ok"] is True, conta
    caixa = next(p for p in extrato.posicoes if p.classe == "CAIXA")
    assert caixa.valor_mercado == pytest.approx(novo_saldo)
    assert novo_saldo == pytest.approx(round(CAIXA_FIM_FIXTURE + 1000.00, 2))
