import { useCallback, useEffect, useState } from 'react'
import { CircleAlert, FilePlus2, FileStack, Lock, Trash2 } from 'lucide-react'
import {
  excluirMes,
  excluirRegra,
  getHistoricoExtratos,
  listarRegras,
  type ExtratoResumo,
  type Regra,
} from '../../lib/api'
import { fmtBRL, fmtData, fmtMes, fmtMesLongo } from '../../lib/format'
import Card from '../dashboard/Card'
import { useToast } from '../Toasts'
import BadgeStatus from './BadgeStatus'
import CompararMeses from './CompararMeses'
import DetalheMes from './DetalheMes'
import ModalLote from './ModalLote'

interface Props {
  chaveRecarga: number
  /** Import do mês pelo chat — com o arquivo já escolhido, quando vier do lote. */
  onImportar(arquivo?: File): void
}

export default function AbaExtratos({ chaveRecarga, onImportar }: Props) {
  const toast = useToast()
  const [meses, setMeses] = useState<ExtratoResumo[] | null>(null)
  const [regras, setRegras] = useState<Regra[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [aberto, setAberto] = useState<string | null>(null)
  const [loteAberto, setLoteAberto] = useState(false)
  const [excluindo, setExcluindo] = useState<ExtratoResumo | null>(null)

  const carregar = useCallback(async () => {
    setErro(null)
    try {
      const [lista, rs] = await Promise.all([getHistoricoExtratos(), listarRegras()])
      setMeses(lista)
      setRegras(rs.filter((r) => r.escopo === 'texto'))
    } catch (e) {
      setErro((e as Error).message)
    }
  }, [])

  useEffect(() => {
    void carregar()
  }, [carregar, chaveRecarga])

  async function confirmarExclusao() {
    if (!excluindo) return
    try {
      await excluirMes(excluindo.data_referencia)
      toast('ok', `Extrato de ${fmtMesLongo(excluindo.data_referencia)} excluído do histórico.`)
      if (aberto === excluindo.data_referencia) setAberto(null)
      setExcluindo(null)
      void carregar()
    } catch (e) {
      toast('erro', (e as Error).message)
      setExcluindo(null)
    }
  }

  async function apagarRegra(r: Regra) {
    try {
      await excluirRegra(r.id)
      toast('ok', 'Regra removida — os lançamentos voltam à classificação padrão.')
      void carregar()
    } catch (e) {
      toast('erro', (e as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setLoteAberto(true)}
          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-[13px] font-medium text-white transition-all hover:brightness-110"
        >
          <FileStack size={15} />
          Enviar extratos antigos
        </button>
        <button
          onClick={() => onImportar()}
          className="hairline flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <FilePlus2 size={15} />
          Importar o mês pelo chat
        </button>
        <p className="w-full text-[12px] text-ink-3 sm:ml-2 sm:w-auto">
          Meses antigos só entram no histórico. O mês mais novo passa pelo chat, que atualiza a carteira.
        </p>
      </div>

      {erro && (
        <Card>
          <p className="text-[13px] text-critical">Não consegui carregar os extratos: {erro}</p>
        </Card>
      )}

      {!erro && meses === null && <div className="shimmer h-48 rounded-xl" />}

      {meses && meses.length === 0 && (
        <Card>
          <p className="py-4 text-center text-[13px] text-ink-3">
            Nenhum extrato arquivado ainda. Envie os meses antigos de uma vez pelo botão acima.
          </p>
        </Card>
      )}

      {meses && meses.length > 0 && (
        <Card titulo={`Extratos arquivados (${meses.length})`}>
          <div className="-mx-4 overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-[12.5px]">
              <thead>
                <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
                  <th className="px-4 pb-2 text-left font-semibold">Mês</th>
                  <th className="px-4 pb-2 text-left font-semibold">Situação</th>
                  <th className="px-4 pb-2 text-right font-semibold">Patrimônio</th>
                  <th className="px-4 pb-2 text-right font-semibold">Posições</th>
                  <th className="px-4 pb-2 text-right font-semibold">Lançamentos</th>
                  <th className="px-4 pb-2 text-right font-semibold">Proventos</th>
                  <th className="px-4 pb-2" />
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {meses.map((m) => {
                  const selecionado = aberto === m.data_referencia
                  return (
                    <tr
                      key={m.id}
                      className={`border-t border-line transition-colors ${
                        selecionado ? 'bg-surface-2' : 'hover:bg-surface-2/60'
                      }`}
                    >
                      <td className="px-4 py-2">
                        <button
                          onClick={() => setAberto(selecionado ? null : m.data_referencia)}
                          className="text-left font-medium text-ink hover:underline"
                          aria-expanded={selecionado}
                        >
                          {m.periodo_mensal ? fmtMes(m.data_referencia) : `até ${fmtData(m.data_referencia)}`}
                        </button>
                        {m.protegido && (
                          <span className="ml-2 text-[11px] text-ink-3" title="É o mês que a carteira reflete hoje">
                            carteira atual
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <span className="inline-flex items-center gap-1.5">
                          <BadgeStatus status={m.status} />
                          {(m.validacao_veredito === 'erro' ||
                            m.validacao_veredito === 'aviso') && (
                            <span
                              className={
                                m.validacao_veredito === 'erro'
                                  ? 'text-critical'
                                  : 'text-warn'
                              }
                              title={`Conferência do extrato com ${
                                m.validacao_veredito === 'erro'
                                  ? m.validacao_erros
                                    ? `${m.validacao_erros} erro(s)`
                                    : 'erro(s)'
                                  : 'aviso(s)'
                              } — abra o mês para ver os checks.`}
                            >
                              <CircleAlert
                                size={13}
                                aria-label="Conferência do extrato com pendências"
                              />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right text-ink">{fmtBRL(m.patrimonio)}</td>
                      <td className="px-4 py-2 text-right text-ink-2">{m.total_posicoes}</td>
                      <td className="px-4 py-2 text-right text-ink-2">
                        {m.tem_lancamentos ? m.lancamentos : '—'}
                        {m.nao_classificados > 0 && (
                          <span className="text-ink-3"> · {m.nao_classificados} a classificar</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right text-ink-2">{fmtBRL(m.proventos_total)}</td>
                      <td className="px-4 py-2 text-right">
                        {m.protegido ? (
                          <span
                            className="inline-flex p-1.5 text-ink-3"
                            title="Este é o mês que a carteira reflete hoje e não pode ser excluído."
                          >
                            <Lock size={13} aria-label="Não pode ser excluído" />
                          </span>
                        ) : (
                          <button
                            onClick={() => setExcluindo(m)}
                            title="Excluir do histórico"
                            aria-label={`Excluir ${fmtMes(m.data_referencia)} do histórico`}
                            className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-3 hover:text-critical"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {aberto && (
        <DetalheMes data={aberto} onFechar={() => setAberto(null)} onMudou={() => void carregar()} />
      )}

      {meses && meses.length > 1 && <CompararMeses meses={meses} />}

      {regras.length > 0 && (
        <Card titulo="Suas regras de classificação">
          <ul className="divide-y divide-line text-[12.5px]">
            {regras.map((r) => (
              <li key={r.id} className="flex items-center gap-3 py-2">
                <span className="min-w-0 flex-1 text-ink-2">
                  {r.sinal === 'credito' ? 'Créditos' : r.sinal === 'debito' ? 'Débitos' : 'Lançamentos'}{' '}
                  {r.modo === 'exato' ? 'iguais a' : r.modo === 'contem' ? 'que contêm' : 'que começam com'}{' '}
                  <span className="text-ink">“{r.padrao}”</span> → <span className="text-ink">{r.rotulo}</span>
                </span>
                <button
                  onClick={() => void apagarRegra(r)}
                  title="Remover regra"
                  aria-label="Remover regra"
                  className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-3 hover:text-critical"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {excluindo && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={(e) => e.target === e.currentTarget && setExcluindo(null)}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label="Excluir extrato do histórico"
            className="hairline fade-up w-full max-w-[420px] rounded-2xl bg-surface p-5"
          >
            <h2 className="text-[15px] font-semibold">
              Excluir o extrato de {fmtMesLongo(excluindo.data_referencia)}?
            </h2>
            <p className="mt-2 text-[13px] text-ink-2">
              Sai do histórico e da série de desempenho, junto com as classificações feitas só
              para as linhas dele. A carteira não muda. Dá para enviar o XLSX de novo depois.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setExcluindo(null)}
                className="rounded-lg px-4 py-2 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
              >
                Cancelar
              </button>
              <button
                onClick={() => void confirmarExclusao()}
                className="rounded-lg bg-critical px-4 py-2 text-[13px] font-medium text-white transition-all hover:brightness-110"
              >
                Excluir
              </button>
            </div>
          </div>
        </div>
      )}

      <ModalLote
        aberto={loteAberto}
        onFechar={() => setLoteAberto(false)}
        onArquivou={() => void carregar()}
        onImportarPeloChat={(f) => onImportar(f)}
      />
    </div>
  )
}
