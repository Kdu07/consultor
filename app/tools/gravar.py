"""
Tool gravar_posicoes — salva as posições do preview no banco de dados.

Guardrail 4 (PLANO §3): esta tool SÓ deve ser chamada no turno de confirmação,
após o usuário dizer "sim" explicitamente. A arquitetura garante isso: a gravação
existe apenas aqui, não em importar_extrato.

Validação por gravidade (plano "Confiabilidade dos extratos"): o staging guarda o payload
de anexar_validacao em estado["bruto"]["validacao"]. Veredito "erro" (divergência acima de
R$ 1,00 entre o que o parser leu e o que o próprio extrato declara) BLOQUEIA a gravação —
nada é escrito e o staging fica como está, para o usuário poder perguntar o que falhou.
Veredito "aviso" grava e repassa as mensagens em result["avisos"]. Staging sem bruto ou
sem validacao (gravação manual, testes, staging antigo) grava como sempre.

Atomicidade: qualquer erro por item invalida o lote INTEIRO — session.rollback() e
tool_error, nada parcial no banco. Vale para o lote do extrato e para a gravação manual.

Fonte da verdade: o preview em extrato_staging, não a lista que o modelo reescreve.
O modelo repetir 15 posições no argumento da tool é um caminho de perda de dados
(truncar a lista, arredondar valores) — e, com reconciliação, uma lista truncada
desativaria posições boas. O argumento `posicoes` continua aceito para gravação
manual (sem extrato em staging) e serve de conferência quando há staging.

Lógica de upsert: casa por `chave_externa` (identidade do papel), com fallback
ticker → nome para as linhas anteriores à migração — ver _achar_posicao.

Reconciliação (lote de extrato): o extrato é a carteira completa na data de
referência, então toda posição ativa fora do lote é marcada ativo=False. Sem isso
a carteira nunca "encolhe": ativos vendidos, resgatados ou vindos do seed inicial
ficam somando no dashboard para sempre. Isso vale inclusive para posições criadas à
mão em POST /posicoes — decisão consciente: o extrato do BTG manda na carteira toda.

Arquivamento (lote de extrato): o upsert acima é destrutivo — o valor do mês anterior
é sobrescrito e nunca mais volta. Antes do commit, app/tools/extrato_arquivo.py guarda
o extrato inteiro em ExtratoImportado, idempotente por data de referência. Tudo na mesma
transação: ou o mês entra completo (posições + histórico) ou não entra.

Extrato retroativo: com o histórico existindo, subir extratos antigos para preenchê-lo
vira coisa natural — e seria destrutivo, porque a reconciliação leria a foto de março
como "a carteira agora" e desativaria tudo o que foi comprado depois. Por isso, um
extrato anterior à data de corte entra em modo somente-histórico: arquiva o mês e não
toca em nenhuma posição. O corte é o mais novo entre o
extrato arquivado mais recente e a data que a carteira reflete (ReferenciaCarteira — ver
extrato_arquivo.data_de_corte); o import no modo normal atualiza essa data.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from ..database import engine
from ..models.posicao import ClasseAtivo, Posicao
from . import extrato_staging
from .extrato_arquivo import (
    arquivar_extrato,
    data_de_corte,
    parse_data_referencia,
    registrar_referencia,
)
from .schemas import tool_error

logger = logging.getLogger(__name__)


def _parse_classe(classe_str: str) -> ClasseAtivo:
    try:
        return ClasseAtivo(classe_str.upper())
    except ValueError:
        return ClasseAtivo.RF


def _parse_date(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        if isinstance(s, str):
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return s
    except Exception:
        return None


def _achar_posicao(session: Session, chave: str | None, ticker: str | None, nome: str) -> Posicao | None:
    """
    Identidade em cascata, da mais estável para a mais frágil:
      1. chave_externa — identidade do papel, imune à reescrita de nome pelo BTG
      2. ticker        — posições anteriores à chave e as criadas à mão
      3. nome          — último recurso (RF/FUNDO/CAIXA antigos, sem ticker)
    Casando por 2 ou 3, quem chama grava a chave na linha: o banco se migra sozinho
    no primeiro import, sem backfill adivinhando papel a partir do nome.
    """
    def _uma(condicao):
        return session.exec(
            select(Posicao).where(condicao).where(Posicao.ativo == True)
        ).first()

    if chave:
        achada = _uma(Posicao.chave_externa == chave)
        if achada:
            return achada
        # Papel que voltou à carteira (vendido e recomprado, RF que rolou): reativa a
        # linha original em vez de abrir outra. Só a chave autoriza isso — ressuscitar
        # por nome traria de volta lixo que a reconciliação tinha acabado de baixar.
        inativa = session.exec(
            select(Posicao)
            .where(Posicao.chave_externa == chave)
            .where(Posicao.ativo == False)
            .order_by(Posicao.atualizado_em.desc())
        ).first()
        if inativa:
            return inativa
        # Uma linha com OUTRA chave é outro papel — nome ou ticker iguais são coincidência
        # (dois CDBs do mesmo banco com vencimentos diferentes têm o mesmo nome curto).
    if ticker:
        achada = _uma(Posicao.ticker == ticker)
        if achada and not (chave and achada.chave_externa and achada.chave_externa != chave):
            return achada
    achada = _uma(Posicao.nome == nome)
    if achada and not (chave and achada.chave_externa and achada.chave_externa != chave):
        return achada
    return None


def _resolver_lote(posicoes: list[dict] | None) -> tuple[list[dict], dict | None, str | None]:
    """
    Decide o que gravar: (lote, estado_do_staging, aviso).

    Com extrato em staging, o preview é a fonte da verdade e o lote é completo —
    a reconciliação e o arquivamento podem rodar. Sem staging, grava-se o que o modelo
    passou, nenhuma posição é desativada e nada é arquivado (não é um mês fechado).

    O estado é lido uma única vez e devolvido inteiro: quem chama precisa do `bruto` e
    do `arquivo` para arquivar, e reler o singleton no meio da gravação abriria janela
    para outro upload trocar o preview no meio do caminho.
    """
    estado = extrato_staging.get()
    if not estado:
        return (posicoes or []), None, None

    preview = estado["preview"].get("posicoes") or []
    aviso = None
    if posicoes is not None and len(posicoes) != len(preview):
        aviso = (
            f"A lista enviada tinha {len(posicoes)} posição(ões) e o extrato em staging "
            f"tem {len(preview)}. Gravei as {len(preview)} do extrato."
        )
        logger.warning("gravar_posicoes: %s", aviso)
    return preview, estado, aviso


async def tool_gravar_posicoes(posicoes: list[dict] | None = None) -> dict:
    """
    Grava as posições confirmadas pelo usuário no banco.
    Nunca deve ser chamada sem confirmação explícita ("sim").
    """
    lote, estado, aviso_lote = _resolver_lote(posicoes)
    veio_do_extrato = estado is not None
    if not lote:
        return tool_error(
            "Nada a gravar: nenhum extrato em staging e nenhuma posição informada. "
            "Peça ao usuário para enviar o XLSX pelo botão 'Importar extrato BTG'."
        )

    # Veredito do validador de invariantes — ver docstring do módulo. A ausência de
    # bruto/validacao é tolerada de propósito (staging antigo, testes, gravação manual).
    validacao = ((estado or {}).get("bruto") or {}).get("validacao") or {}
    if validacao.get("veredito") == "erro":
        reprovados = validacao.get("erros") or [
            f"{c.get('id')} — {c.get('rotulo')}: esperado {c.get('esperado')}, "
            f"obtido {c.get('obtido')} (diferença {c.get('diferenca')})"
            for c in validacao.get("checks") or []
            if (c or {}).get("severidade") == "erro"
        ] or ["o validador reprovou o extrato sem detalhar os checks"]
        logger.warning(
            "gravar_posicoes: extrato reprovado na validação (%d erro(s)) — nada gravado",
            len(reprovados),
        )
        return tool_error(
            f"O extrato REPROVOU na validação de invariantes ({len(reprovados)} "
            "conferência(s) com divergência acima de R$ 1,00):\n- "
            + "\n- ".join(reprovados)
            + "\nNada foi gravado. Confira o arquivo no app BTG e reenvie; se o BTG "
            "estiver mesmo divergente, fale com o dono do sistema."
        )
    avisos_validacao = list(validacao.get("avisos") or [])

    now = datetime.now(timezone.utc)
    criados = 0
    atualizados = 0
    erros: list[str] = []
    reativadas: list[str] = []
    ids_no_lote: set[int] = set()

    with Session(engine) as session:
        # Antes de escrever qualquer posição: este extrato é do mês corrente da carteira
        # ou é um mês antigo sendo arquivado? Só a segunda pergunta muda o fluxo.
        data_ref = parse_data_referencia((estado or {}).get("preview", {}).get("data_referencia"))
        corte = data_de_corte(session) if veio_do_extrato else None
        somente_historico = (
            veio_do_extrato
            and data_ref is not None
            and corte is not None
            and data_ref < corte
        )

        # Em modo somente-histórico o lote não é percorrido: nenhuma posição é criada,
        # atualizada ou desativada — o extrato antigo só alimenta o arquivo lá embaixo.
        for item in ([] if somente_historico else lote):
            try:
                ticker = (item.get("ticker") or "").strip() or None
                nome = (item.get("nome") or "").strip()
                classe = _parse_classe(item.get("classe", "RF"))
                quantidade = float(item.get("quantidade", 0))
                preco_medio = item.get("preco_medio")
                valor_mercado = item.get("valor_mercado")
                as_of = _parse_date(item.get("as_of"))
                # Renda fixa: vencimento e taxa vêm do extrato XLSX (podem ser None em RV)
                vencimento = _parse_date(item.get("vencimento"))
                taxa_contratada = (item.get("taxa_contratada") or "").strip() or None
                chave_externa = (item.get("chave_externa") or "").strip() or None

                if not nome:
                    erros.append(f"Posição sem nome ignorada: {item}")
                    continue

                existing = _achar_posicao(session, chave_externa, ticker, nome)

                if existing:
                    if not existing.ativo:
                        existing.ativo = True
                        reativadas.append(existing.ticker or nome)
                    existing.chave_externa = chave_externa or existing.chave_externa
                    existing.nome = nome
                    existing.ticker = ticker
                    existing.classe = classe
                    existing.quantidade = quantidade
                    existing.preco_medio = float(preco_medio) if preco_medio is not None else None
                    existing.valor_mercado = float(valor_mercado) if valor_mercado is not None else None
                    existing.vencimento = vencimento
                    existing.taxa_contratada = taxa_contratada
                    existing.source = "extrato"
                    existing.as_of = as_of
                    existing.atualizado_em = now
                    session.add(existing)
                    atualizados += 1
                    if existing.id is not None:
                        ids_no_lote.add(existing.id)
                else:
                    nova = Posicao(
                        chave_externa=chave_externa,
                        ticker=ticker,
                        nome=nome,
                        classe=classe,
                        quantidade=quantidade,
                        preco_medio=float(preco_medio) if preco_medio is not None else None,
                        valor_mercado=float(valor_mercado) if valor_mercado is not None else None,
                        vencimento=vencimento,
                        taxa_contratada=taxa_contratada,
                        source="extrato",
                        as_of=as_of,
                        atualizado_em=now,
                    )
                    session.add(nova)
                    # flush para obter o id e não desativar a posição recém-criada
                    session.flush()
                    criados += 1
                    if nova.id is not None:
                        ids_no_lote.add(nova.id)

            except Exception as e:
                erros.append(f"Erro ao processar '{item.get('ticker', item.get('nome', '?'))}': {e}")

        # Atomicidade: erro em QUALQUER item invalida o lote inteiro. Antes havia commit
        # incondicional mesmo com erros — estado parcial no banco (e a reconciliação
        # pulada deixava a carteira inconsistente em silêncio). Agora: rollback e
        # tool_error; o staging (se houver) fica para o usuário perguntar o que falhou.
        if erros:
            session.rollback()
            logger.warning(
                "gravar_posicoes: %d erro(s) no lote — rollback, nada foi gravado", len(erros)
            )
            return tool_error(
                "NENHUMA posição foi gravada — a gravação é tudo-ou-nada e houve erro "
                "no lote:\n- " + "\n- ".join(erros)
                + ("\nO extrato continua em staging: corrija o problema e confirme de novo."
                   if veio_do_extrato else "")
            )

        # Reconciliação: o extrato é a carteira completa naquela data de referência.
        # Só roda em lote de extrato (erro no lote já retornou acima).
        desativadas: list[dict] = []
        if veio_do_extrato and not somente_historico:
            ausentes = session.exec(
                select(Posicao).where(Posicao.ativo == True)
            ).all()
            for p in ausentes:
                if p.id in ids_no_lote:
                    continue
                p.ativo = False
                p.atualizado_em = now
                session.add(p)
                desativadas.append({
                    "ticker": p.ticker,
                    "nome": p.nome,
                    "classe": p.classe.value,
                    "ultimo_valor": p.valor_mercado,
                })

        # Arquivamento: guarda o mês antes que o próximo import sobrescreva estes
        # valores. Roda nos dois modos — é justamente o que o import retroativo veio
        # fazer. (Lote com erro não chega aqui: o rollback acima já devolveu tool_error.)
        arquivo_info: dict | None = None
        avisos_arquivo: list[str] = []
        if veio_do_extrato:
            preview = estado["preview"]
            if data_ref is None:
                avisos_arquivo.append(
                    "Extrato sem data de referência legível — as posições foram gravadas, "
                    "mas o mês NÃO foi arquivado no histórico."
                )
            else:
                registro, novo = arquivar_extrato(
                    session, preview, estado.get("bruto"), estado.get("arquivo"), data_ref, now,
                )
                session.flush()
                arquivo_info = {
                    "data_referencia": data_ref.isoformat(),
                    "id": registro.id,
                    "acao": "criado" if novo else "atualizado",
                    "proventos_total": registro.proventos_total,
                    "proventos_quantidade": registro.proventos_quantidade,
                }
                if not somente_historico:
                    # A carteira passou a refletir este extrato: é o novo corte.
                    registrar_referencia(session, data_ref, now=now)

        session.commit()

    # O preview é de uso único: consumido, sai do staging. Assim uma gravação manual
    # posterior ("adicione tal posição") não é confundida com o lote do extrato.
    # (Só se chega aqui em sucesso — erro no lote retornou antes do commit, com staging.)
    if veio_do_extrato:
        extrato_staging.clear()

    logger.info(
        "gravar_posicoes: %d criadas, %d atualizadas, %d reativadas, %d desativadas, "
        "extrato_arquivado=%s",
        criados, atualizados, len(reativadas), len(desativadas),
        (arquivo_info or {}).get("data_referencia"),
    )

    result: dict = {
        "posicoes_criadas": criados,
        "posicoes_atualizadas": atualizados,
        "total_gravadas": criados + atualizados,
        "posicoes_desativadas": desativadas,
        "posicoes_reativadas": reativadas,
        "data_gravacao": now.isoformat(),
        "source": "extrato",
    }
    if arquivo_info:
        result["extrato_arquivado"] = arquivo_info
    if somente_historico:
        result["modo"] = "somente_historico"
        result["carteira_alterada"] = False

    # Avisos da validação primeiro (o modelo os repete ao usuário), depois os do fluxo.
    avisos = avisos_validacao + avisos_arquivo
    if somente_historico:
        avisos.append(
            f"Extrato de {data_ref.isoformat()}, anterior à data que a carteira já reflete "
            f"({corte.isoformat()}): arquivei o mês no histórico e NÃO mexi na "
            f"carteira atual. DIGA isso ao usuário — se ele quis mesmo voltar a carteira "
            f"para essa data, é preciso fazer isso de propósito, não por um import."
        )
    if aviso_lote:
        avisos.append(aviso_lote)
    if desativadas:
        nomes = ", ".join(d["ticker"] or d["nome"] for d in desativadas)
        avisos.append(
            f"{len(desativadas)} posição(ões) não apareceram neste extrato e saíram da "
            f"carteira: {nomes}. DIGA isso ao usuário — pode ser venda/resgate, mas também "
            f"pode ser ativo em outra corretora que o extrato do BTG não cobre."
        )
    if reativadas:
        avisos.append(
            f"Voltaram à carteira depois de terem saído em algum extrato anterior: "
            f"{', '.join(reativadas)}."
        )
    if avisos:
        result["avisos"] = avisos
    return result
