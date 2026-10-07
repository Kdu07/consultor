import { useEffect, useRef, useState } from 'react'
import { CircleAlert, CircleCheck, CircleSlash, FileSpreadsheet, Upload, X } from 'lucide-react'
import {
  confirmarLote,
  descartarLote,
  enviarLote,
  type ItemLote,
  type Lote,
  type ResultadoLote,
  type StatusItemLote,
} from '../../lib/api'
import { fmtBRL, fmtData, fmtMes, fmtPctSinal } from '../../lib/format'

interface Props {
  aberto: boolean
  onFechar(): void
  /** Algo foi arquivado: a lista precisa recarregar. */
  onArquivou(): void
  /** Mês mais novo que a carteira: vai para o import pelo chat, com o mesmo arquivo. */
  onImportarPeloChat(arquivo: File): void
}

const STATUS: Record<StatusItemLote, string> = {
  novo: 'Novo no histórico',
  substitui: 'Substitui o arquivado',
  reenvio_do_atual: 'Mês atual da carteira',
  diverge_da_carteira: 'Diverge da carteira',
  mais_novo_que_carteira: 'Mais novo que a carteira',
  periodo_nao_mensal: 'Não é um mês inteiro',
  duplicado_no_lote: 'Repetido no lote',
  erro: 'Não foi lido',
}

const MAX_ARQUIVOS = 24

/**
 * Meses antigos de uma vez (decisão 7 do dono): o lote só ARQUIVA — nunca mexe
 * na carteira — e a confirmação é aqui, num clique, em vez do "sim" no chat.
 * O servidor reavalia tudo no clique.
 */
export default function ModalLote({ aberto, onFechar, onArquivou, onImportarPeloChat }: Props) {
  const [arquivos, setArquivos] = useState<File[]>([])
  const [lote, setLote] = useState<Lote | null>(null)
  const [marcados, setMarcados] = useState<Set<string>>(new Set())
  const [enviando, setEnviando] = useState(false)
  const [confirmando, setConfirmando] = useState(false)
  const [resultado, setResultado] = useState<ResultadoLote | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [arrastando, setArrastando] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const fecharRef = useRef(onFechar)
  fecharRef.current = onFechar

  useEffect(() => {
    if (!aberto) return
    setArquivos([])
    setLote(null)
    setMarcados(new Set())
    setResultado(null)
    setErro(null)
    setEnviando(false)
    setConfirmando(false)
    function esc(e: KeyboardEvent) {
      if (e.key === 'Escape') fecharRef.current()
    }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [aberto])

  if (!aberto) return null

  function escolher(lista: FileList | null) {
    if (!lista) return
    const xlsx = Array.from(lista).filter((f) => f.name.toLowerCase().endsWith('.xlsx'))
    if (xlsx.length < lista.length) setErro('Só arquivos .xlsx entram no lote — os outros ficaram de fora.')
    else setErro(null)
    setArquivos((atuais) => [...atuais, ...xlsx].slice(0, MAX_ARQUIVOS))
  }

  async function enviar() {
    setEnviando(true)
    setErro(null)
    try {
      const l = await enviarLote(arquivos)
      setLote(l)
      setMarcados(
        new Set(l.itens.filter((i) => i.selecionado_padrao && i.data_referencia).map((i) => i.data_referencia!)),
      )
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setEnviando(false)
    }
  }

  async function confirmar() {
    if (!lote) return
    setConfirmando(true)
    setErro(null)
    try {
      const r = await confirmarLote(lote.id, [...marcados])
      setResultado(r)
      if (r.arquivados.length) onArquivou()
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setConfirmando(false)
    }
  }

  function fechar() {
    if (lote && !resultado) void descartarLote(lote.id)
    onFechar()
  }

  function alternar(item: ItemLote) {
    if (!item.selecionavel || !item.data_referencia) return
    setMarcados((m) => {
      const novo = new Set(m)
      if (novo.has(item.data_referencia!)) novo.delete(item.data_referencia!)
      else novo.add(item.data_referencia!)
      return novo
    })
  }

  // O servidor devolve os itens na ordem do envio: o File de cada um é o mesmo índice.
  const arquivoDoItem = (i: number) => arquivos[i]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && fechar()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Enviar extratos antigos"
        className="hairline fade-up flex max-h-[90dvh] w-full max-w-[760px] flex-col rounded-2xl bg-surface shadow-[0_24px_64px_rgba(0,0,0,0.6)]"
      >
        <div className="flex items-start gap-3 p-5 pb-3">
          <div className="flex-1">
            <h2 className="text-[16px] font-semibold">Enviar extratos antigos</h2>
            <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
              Vários XLSX de uma vez, para preencher o histórico. Eles{' '}
              <strong className="font-medium text-ink">só entram no histórico — a carteira não muda</strong>.
              Um mês mais novo que a carteira continua pelo chat.
            </p>
          </div>
          <button
            onClick={fechar}
            className="rounded-md p-1 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
            aria-label="Fechar"
          >
            <X size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-2">
          {!lote && (
            <>
              <button
                onClick={() => inputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  setArrastando(true)
                }}
                onDragLeave={() => setArrastando(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setArrastando(false)
                  escolher(e.dataTransfer.files)
                }}
                className={`flex w-full flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-7 transition-colors ${
                  arrastando
                    ? 'border-accent bg-accent-soft/40'
                    : 'border-surface-3 bg-surface-2/50 hover:border-ink-3'
                }`}
              >
                <Upload size={22} className="text-ink-3" />
                <span className="text-[13px] text-ink-2">
                  Arraste os .xlsx aqui ou clique para escolher (até {MAX_ARQUIVOS})
                </span>
              </button>
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx"
                multiple
                className="hidden"
                onChange={(e) => {
                  escolher(e.target.files)
                  e.target.value = ''
                }}
              />
              {arquivos.length > 0 && (
                <ul className="mt-3 space-y-1 text-[12.5px] text-ink-2">
                  {arquivos.map((f, i) => (
                    <li key={`${f.name}-${i}`} className="flex items-center gap-2">
                      <FileSpreadsheet size={14} className="shrink-0 text-ink-3" />
                      <span className="truncate">{f.name}</span>
                      <span className="text-ink-3">{(f.size / 1024).toFixed(0)} KB</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {lote && !resultado && (
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-[12.5px]">
                <thead>
                  <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
                    <th className="w-8 px-5 py-2" />
                    <th className="px-2 py-2 text-left font-semibold">Mês</th>
                    <th className="px-2 py-2 text-left font-semibold">Situação</th>
                    <th className="px-2 py-2 text-right font-semibold">Patrimônio</th>
                    <th className="px-2 py-2 text-right font-semibold">Lançamentos</th>
                    <th className="px-5 py-2 text-right font-semibold">Rent.</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {lote.itens.map((item, i) => {
                    const marcado = !!item.data_referencia && marcados.has(item.data_referencia)
                    return (
                      <tr key={i} className="border-t border-line align-top">
                        <td className="px-5 py-2">
                          <input
                            type="checkbox"
                            checked={marcado}
                            disabled={!item.selecionavel}
                            onChange={() => alternar(item)}
                            aria-label={`Arquivar ${fmtMes(item.data_referencia)}`}
                          />
                        </td>
                        <td className="px-2 py-2">
                          <div className="font-medium text-ink">
                            {item.data_referencia ? fmtMes(item.data_referencia) : '—'}
                          </div>
                          <div className="max-w-[160px] truncate text-[11px] text-ink-3">{item.arquivo}</div>
                        </td>
                        <td className="px-2 py-2">
                          <SituacaoItem item={item} />
                          {item.mensagem && <p className="mt-0.5 max-w-[280px] text-[11px] text-ink-3">{item.mensagem}</p>}
                          {item.completa_lancamentos && (
                            <p className="mt-0.5 text-[11px] text-ink-3">completa os lançamentos que faltavam</p>
                          )}
                          {item.avisos.map((a) => (
                            <p key={a} className="mt-0.5 max-w-[280px] text-[11px] text-ink-3">
                              {a}
                            </p>
                          ))}
                          {/* O backend já promove erros[0] a `mensagem`; não repetir. */}
                          {(item.validacao?.erros ?? [])
                            .filter((e) => e !== item.mensagem)
                            .map((e) => (
                              <p key={e} className="mt-0.5 max-w-[280px] text-[11px] text-critical">
                                {e}
                              </p>
                            ))}
                          {item.status === 'mais_novo_que_carteira' && arquivoDoItem(i) && (
                            <button
                              onClick={() => {
                                const f = arquivoDoItem(i)
                                void descartarLote(lote.id)
                                onFechar()
                                onImportarPeloChat(f)
                              }}
                              className="mt-1 text-[11.5px] text-accent hover:underline"
                            >
                              Importar pelo chat
                            </button>
                          )}
                        </td>
                        <td className="px-2 py-2 text-right text-ink-2">{fmtBRL(item.patrimonio)}</td>
                        <td className="px-2 py-2 text-right text-ink-2">
                          {item.lancamentos ?? '—'}
                          {item.nao_classificados ? (
                            <span className="text-ink-3"> · {item.nao_classificados} a classificar</span>
                          ) : null}
                        </td>
                        <td className="px-5 py-2 text-right text-ink-2">{fmtPctSinal(item.rentabilidade_pct)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {resultado && (
            <div className="space-y-2 text-[13px]">
              {resultado.arquivados.length > 0 && (
                <p className="flex items-start gap-2 text-ink">
                  <CircleCheck size={15} className="mt-0.5 shrink-0 text-good" />
                  {resultado.arquivados.length} mês(es) no histórico:{' '}
                  {resultado.arquivados.map((a) => fmtMes(a.data_referencia)).join(', ')}. A carteira não mudou.
                </p>
              )}
              {resultado.recusados.map((r) => (
                <p key={r.data_referencia} className="flex items-start gap-2 text-ink-2">
                  <CircleAlert size={15} className="mt-0.5 shrink-0 text-warn" />
                  {fmtMes(r.data_referencia)}: {r.mensagem ?? STATUS[r.motivo as StatusItemLote] ?? r.motivo}
                </p>
              ))}
            </div>
          )}

          {erro && (
            <p className="mt-3 flex items-start gap-2 rounded-lg bg-surface-2 p-2.5 text-[13px] text-critical">
              <CircleAlert size={14} className="mt-0.5 shrink-0" />
              {erro}
            </p>
          )}
        </div>

        <div className="hairline-t flex items-center justify-end gap-2 p-4">
          {lote && !resultado && (
            <p className="mr-auto text-[12px] text-ink-3">
              Carteira em {lote.data_corte ? fmtData(lote.data_corte) : '—'}: só entram meses até essa data.
            </p>
          )}
          {!resultado && (
            <button
              onClick={fechar}
              className="rounded-lg px-4 py-2 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
            >
              Cancelar
            </button>
          )}
          {!lote && (
            <button
              onClick={() => void enviar()}
              disabled={arquivos.length === 0 || enviando}
              className="rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition-all enabled:hover:brightness-110 disabled:bg-surface-3 disabled:text-ink-3"
            >
              {enviando ? 'Lendo extratos…' : `Ler ${arquivos.length || ''} extrato(s)`}
            </button>
          )}
          {lote && !resultado && (
            <button
              onClick={() => void confirmar()}
              disabled={marcados.size === 0 || confirmando}
              className="rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition-all enabled:hover:brightness-110 disabled:bg-surface-3 disabled:text-ink-3"
            >
              {confirmando ? 'Arquivando…' : `Arquivar ${marcados.size} ${marcados.size === 1 ? 'mês' : 'meses'}`}
            </button>
          )}
          {resultado && (
            <button
              onClick={onFechar}
              className="rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition-all hover:brightness-110"
            >
              Concluir
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function SituacaoItem({ item }: { item: ItemLote }) {
  const Icone = item.selecionavel ? CircleCheck : item.status === 'erro' ? CircleAlert : CircleSlash
  const cor = item.selecionavel ? 'text-good' : item.status === 'erro' ? 'text-critical' : 'text-ink-3'
  return (
    <span className="inline-flex items-center gap-1.5 text-ink-2">
      <Icone size={13} className={`shrink-0 ${cor}`} aria-hidden="true" />
      {STATUS[item.status]}
    </span>
  )
}
