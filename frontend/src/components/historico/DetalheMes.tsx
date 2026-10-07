import { useCallback, useEffect, useState } from 'react'
import { CircleAlert, CircleCheck, CircleHelp, X } from 'lucide-react'
import {
  criarRegra,
  getExtratoDetalhe,
  getLancamentos,
  type CheckValidacao,
  type ExtratoDetalhe,
  type Lancamento,
  type LancamentosMes,
} from '../../lib/api'
import { corDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtBRLSinal, fmtData, fmtMesLongo, fmtQtde } from '../../lib/format'
import { useToast } from '../Toasts'

/** Tipos de lançamento, agrupados pelo que importa: entrou/saiu da carteira ou não. */
const GRUPOS: { rotulo: string; tipos: [string, string][] }[] = [
  {
    rotulo: 'Entrou ou saiu da carteira',
    tipos: [
      ['APORTE', 'Aporte'],
      ['RESGATE', 'Resgate'],
    ],
  },
  {
    rotulo: 'Movimento interno',
    tipos: [
      ['COMPRA_RV', 'Compra de ativo'],
      ['VENDA_RV', 'Venda de ativo'],
      ['APLICACAO_RF', 'Aplicação em renda fixa'],
      ['RESGATE_RF', 'Resgate de renda fixa'],
      ['OUTRO_INTERNO', 'Outro (interno)'],
    ],
  },
  {
    rotulo: 'Renda',
    tipos: [
      ['PROVENTO', 'Provento'],
      ['ALUGUEL', 'Aluguel de ações'],
      ['RENDIMENTO_CAIXA', 'Rendimento do saldo'],
    ],
  },
  {
    rotulo: 'Custos',
    tipos: [
      ['IMPOSTO', 'Imposto'],
      ['TAXA', 'Taxa'],
    ],
  },
]

const ORIGEM: Record<Lancamento['origem'], string> = {
  linha: 'escolhido para esta linha',
  regra: 'regra sua',
  padrao: 'regra padrão',
  nenhuma: 'a classificar',
}

interface Props {
  data: string
  onFechar(): void
  /** Uma classificação mudou: a lista e o desempenho precisam recarregar. */
  onMudou(): void
}

export default function DetalheMes({ data, onFechar, onMudou }: Props) {
  const toast = useToast()
  const [detalhe, setDetalhe] = useState<ExtratoDetalhe | null>(null)
  const [razao, setRazao] = useState<LancamentosMes | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [edicao, setEdicao] = useState<{ seq: number; tipo: string; escopo: 'linha' | 'texto' } | null>(null)
  const [salvando, setSalvando] = useState(false)

  const carregar = useCallback(async () => {
    setErro(null)
    try {
      const [d, l] = await Promise.all([getExtratoDetalhe(data), getLancamentos(data)])
      setDetalhe(d)
      setRazao(l)
    } catch (e) {
      setErro((e as Error).message)
    }
  }, [data])

  useEffect(() => {
    setDetalhe(null)
    setRazao(null)
    setEdicao(null)
    void carregar()
  }, [carregar])

  async function salvar(l: Lancamento) {
    if (!edicao) return
    setSalvando(true)
    try {
      const r = await criarRegra(
        edicao.escopo === 'linha'
          ? { tipo: edicao.tipo, escopo: 'linha', data_referencia: data, seq: l.seq }
          : {
              tipo: edicao.tipo,
              escopo: 'texto',
              modo: 'prefixo',
              padrao: l.padrao_sugerido,
              sinal: l.valor > 0 ? 'credito' : 'debito',
            },
      )
      const n = r.afetados.lancamentos
      toast(
        'ok',
        edicao.escopo === 'linha'
          ? 'Classificação salva para esta linha.'
          : `Regra salva: vale para ${n} lançamento(s) em ${r.afetados.meses} mês(es).`,
      )
      setEdicao(null)
      await carregar()
      onMudou()
    } catch (e) {
      toast('erro', (e as Error).message)
    } finally {
      setSalvando(false)
    }
  }

  const checagem = detalhe?.extrato.checagem
  const conta = razao?.checagem
  // Validador de invariantes (payload v3+). Payload antigo não traz o campo.
  const validacao = detalhe?.extrato.validacao ?? null
  const checksComProblema =
    validacao?.checks.filter((c) => c.severidade !== 'ok') ?? []

  return (
    <section className="hairline rounded-xl bg-surface p-4">
      <div className="mb-3 flex items-start gap-3">
        <div className="flex-1">
          <h2 className="text-[15px] font-semibold text-ink">
            Extrato de {fmtMesLongo(data)}
          </h2>
          {detalhe && (
            <p className="text-[12px] text-ink-3">
              Fechamento em {fmtData(detalhe.data_referencia)} · {detalhe.total_posicoes} posições ·{' '}
              {fmtBRL(detalhe.patrimonio)}
            </p>
          )}
        </div>
        <button
          onClick={onFechar}
          aria-label="Fechar o detalhe"
          className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <X size={15} />
        </button>
      </div>

      {erro && <p className="text-[13px] text-critical">Não consegui abrir este mês: {erro}</p>}
      {!erro && (!detalhe || !razao) && <div className="shimmer h-40 rounded-lg" />}

      {detalhe && razao && (
        <div className="space-y-5">
          <div className="grid gap-2 text-[12.5px] sm:grid-cols-2">
            <Conferencia
              ok={checagem?.ok ?? null}
              titulo="Posições × Sumário do extrato"
              texto={
                checagem?.ok
                  ? `Bate (diferença de ${fmtBRL(checagem.diferenca)}).`
                  : (checagem?.aviso ?? 'Sem conferência.')
              }
            />
            <Conferencia
              ok={razao.tem_lancamentos ? (conta?.ok ?? null) : null}
              titulo="Razão da conta corrente"
              texto={
                !razao.tem_lancamentos
                  ? 'Arquivo antigo, sem os lançamentos da conta — reenvie o XLSX pelo lote.'
                  : conta?.ok
                    ? 'Saldo inicial + lançamentos = saldo final.'
                    : (conta?.aviso ?? 'Não conferido.')
              }
            />
          </div>

          <div>
            <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
              Conferência do extrato
            </h3>
            {!validacao ? (
              <p className="flex items-start gap-2 text-[12.5px] text-ink-3">
                <CircleHelp size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                Extrato arquivado antes do validador — reenvie o XLSX pelo lote
                para conferir.
              </p>
            ) : checksComProblema.length === 0 ? (
              <p className="flex items-start gap-2 text-[12.5px] text-ink-2">
                <CircleCheck size={14} className="mt-0.5 shrink-0 text-good" aria-hidden="true" />
                Todas as conferências internas fecharam ({validacao.checks.length}{' '}
                checks).
              </p>
            ) : (
              <div className="-mx-4 overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-[12.5px]">
                  <thead>
                    <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
                      <th className="px-4 py-2 text-left font-semibold">Conferência</th>
                      <th className="px-4 py-2 text-right font-semibold">Esperado</th>
                      <th className="px-4 py-2 text-right font-semibold">Obtido</th>
                      <th className="px-4 py-2 text-right font-semibold">Diferença</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {checksComProblema.map((c) => (
                      <tr key={c.id} className="border-t border-line align-top">
                        <td className="px-4 py-2">
                          <span className="flex items-start gap-1.5 text-ink">
                            <IconeCheck severidade={c.severidade} />
                            {c.rotulo}
                          </span>
                          {c.detalhe && (
                            <p className="mt-0.5 text-[11px] text-ink-3">{c.detalhe}</p>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right whitespace-nowrap text-ink-2">
                          {fmtBRL(c.esperado)}
                        </td>
                        <td className="px-4 py-2 text-right whitespace-nowrap text-ink-2">
                          {fmtBRL(c.obtido)}
                        </td>
                        <td className="px-4 py-2 text-right whitespace-nowrap text-ink">
                          {fmtBRLSinal(c.diferenca)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {razao.tem_lancamentos && (
            <div>
              <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                Lançamentos da conta ({razao.lancamentos.length})
              </h3>
              <p className="mb-2 text-[12px] text-ink-3">
                Só aporte e resgate mexem na rentabilidade: são o dinheiro que entrou ou saiu da
                carteira. O resto é movimento interno, renda ou custo.
              </p>
              <div className="-mx-4 overflow-x-auto">
                <table className="w-full min-w-[640px] border-collapse text-[12.5px]">
                  <thead>
                    <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
                      <th className="px-4 py-2 text-left font-semibold">Data</th>
                      <th className="px-4 py-2 text-left font-semibold">Descrição</th>
                      <th className="px-4 py-2 text-right font-semibold">Valor</th>
                      <th className="px-4 py-2 text-left font-semibold">Tipo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {razao.lancamentos.map((l) => {
                      const editando = edicao?.seq === l.seq
                      return (
                        <tr key={l.seq} className="border-t border-line align-top">
                          <td className="px-4 py-2 whitespace-nowrap text-ink-2 tabular-nums">{fmtData(l.data)}</td>
                          <td className="px-4 py-2 text-ink">{l.descricao}</td>
                          <td className="px-4 py-2 text-right whitespace-nowrap text-ink tabular-nums">
                            {l.valor > 0 ? '+' : ''}
                            {fmtBRL(l.valor)}
                          </td>
                          <td className="px-4 py-2">
                            <select
                              value={editando ? edicao!.tipo : l.tipo === 'NAO_CLASSIFICADO' ? '' : l.tipo}
                              onChange={(e) =>
                                setEdicao({
                                  seq: l.seq,
                                  tipo: e.target.value,
                                  escopo:
                                    edicao?.seq === l.seq
                                      ? edicao.escopo
                                      : l.padrao_sugerido
                                        ? 'texto'
                                        : 'linha',
                                })
                              }
                              aria-label={`Tipo do lançamento de ${fmtData(l.data)}`}
                              className={`hairline w-full max-w-[220px] rounded-md bg-surface-2 px-2 py-1 text-[12.5px] ${
                                l.tipo === 'NAO_CLASSIFICADO' && !editando ? 'text-warn' : 'text-ink'
                              }`}
                            >
                              <option value="" disabled>
                                A classificar
                              </option>
                              {GRUPOS.map((g) => (
                                <optgroup key={g.rotulo} label={g.rotulo}>
                                  {g.tipos.map(([valor, rotulo]) => (
                                    <option key={valor} value={valor}>
                                      {rotulo}
                                    </option>
                                  ))}
                                </optgroup>
                              ))}
                            </select>
                            {!editando && (
                              <p className="mt-0.5 flex items-center gap-1 text-[11px] text-ink-3">
                                {l.tipo === 'NAO_CLASSIFICADO' && (
                                  <CircleHelp size={11} className="text-warn" aria-hidden="true" />
                                )}
                                {ORIGEM[l.origem]}
                              </p>
                            )}
                            {editando && (
                              <div className="mt-2 rounded-lg bg-surface-2 p-2 text-[12px]">
                                <p className="mb-1 text-ink-3">Vale para</p>
                                {l.padrao_sugerido && (
                                  <label className="flex items-center gap-2 text-ink-2">
                                    <input
                                      type="radio"
                                      checked={edicao!.escopo === 'texto'}
                                      onChange={() => setEdicao({ ...edicao!, escopo: 'texto' })}
                                    />
                                    todos os {l.valor > 0 ? 'créditos' : 'débitos'} que começam com “
                                    {l.padrao_sugerido}”, inclusive nos próximos meses
                                  </label>
                                )}
                                <label className="mt-1 flex items-center gap-2 text-ink-2">
                                  <input
                                    type="radio"
                                    checked={edicao!.escopo === 'linha'}
                                    onChange={() => setEdicao({ ...edicao!, escopo: 'linha' })}
                                  />
                                  só esta linha
                                </label>
                                <div className="mt-2 flex gap-2">
                                  <button
                                    onClick={() => void salvar(l)}
                                    disabled={salvando}
                                    className="rounded-md bg-accent px-3 py-1 text-[12px] font-medium text-white enabled:hover:brightness-110 disabled:bg-surface-3 disabled:text-ink-3"
                                  >
                                    {salvando ? 'Salvando…' : 'Salvar'}
                                  </button>
                                  <button
                                    onClick={() => setEdicao(null)}
                                    className="rounded-md px-3 py-1 text-[12px] text-ink-2 hover:text-ink"
                                  >
                                    Cancelar
                                  </button>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {detalhe.extrato.proventos.length > 0 && (
            <div>
              <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                Proventos ({fmtBRL(detalhe.proventos_total)})
              </h3>
              <ul className="space-y-1 text-[12.5px]">
                {detalhe.extrato.proventos.map((p, i) => (
                  <li key={i} className="flex justify-between gap-3">
                    <span className="text-ink-2">
                      <span className="text-ink">{p.ticker ?? '—'}</span> · {p.transacao} · {fmtData(p.data)}
                    </span>
                    <span className="tabular-nums text-ink">{fmtBRL(p.valor_liquido ?? p.valor_bruto)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
              Posições no fechamento
            </h3>
            <div className="-mx-4 overflow-x-auto">
              <table className="w-full min-w-[480px] border-collapse text-[12.5px]">
                <tbody className="tabular-nums">
                  {[...detalhe.extrato.posicoes]
                    .sort((a, b) => b.valor_mercado - a.valor_mercado)
                    .map((p, i) => (
                      <tr key={p.chave_externa ?? i} className="border-t border-line">
                        <td className="px-4 py-1.5">
                          <span className="inline-flex items-center gap-2">
                            <span
                              className="size-1.5 rounded-full"
                              style={{ backgroundColor: corDaClasse(p.classe) }}
                              aria-hidden="true"
                            />
                            <span className="text-ink">{p.ticker ?? p.nome}</span>
                            <span className="text-[11px] text-ink-3">{rotuloDaClasse(p.classe)}</span>
                          </span>
                        </td>
                        <td className="px-4 py-1.5 text-right text-ink-2">{fmtQtde(p.quantidade)}</td>
                        <td className="px-4 py-1.5 text-right text-ink">{fmtBRL(p.valor_mercado)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

/** Ícone de um check do validador: erro em crítico, aviso em warn, não avaliável neutro. */
function IconeCheck({ severidade }: { severidade: CheckValidacao['severidade'] }) {
  const Icone = severidade === 'nao_avaliavel' ? CircleHelp : CircleAlert
  const cor =
    severidade === 'erro'
      ? 'text-critical'
      : severidade === 'aviso'
        ? 'text-warn'
        : 'text-ink-3'
  return <Icone size={13} className={`mt-0.5 shrink-0 ${cor}`} aria-label={severidade} />
}

function Conferencia({ ok, titulo, texto }: { ok: boolean | null; titulo: string; texto: string }) {
  const Icone = ok ? CircleCheck : ok === false ? CircleAlert : CircleHelp
  const cor = ok ? 'text-good' : ok === false ? 'text-warn' : 'text-ink-3'
  return (
    <div className="flex items-start gap-2 rounded-lg bg-surface-2 p-2.5">
      <Icone size={14} className={`mt-0.5 shrink-0 ${cor}`} aria-hidden="true" />
      <div>
        <p className="font-medium text-ink">{titulo}</p>
        <p className="text-ink-2">{texto}</p>
      </div>
    </div>
  )
}
