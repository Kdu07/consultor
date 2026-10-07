import { useEffect, useRef, useState } from 'react'
import { FileSpreadsheet, TriangleAlert, Upload, X } from 'lucide-react'
import { enviarExtrato, type PreviewExtrato } from '../lib/api'
import { fmtBRL, fmtData } from '../lib/format'

interface Props {
  aberto: boolean
  /** Arquivo já escolhido (vem do lote: o mês mais novo que a carteira). */
  arquivoInicial?: File | null
  onFechar(): void
  /** Chamado após o upload dar certo — dispara o turno de confirmação no chat. */
  onImportado(): void
}

export default function ModalImport({ aberto, arquivoInicial = null, onFechar, onImportado }: Props) {
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewExtrato | null>(null)
  const [arrastando, setArrastando] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const timerRef = useRef<number | null>(null)
  // Os callbacks ficam em ref: o efeito abaixo depende só de `aberto`. Com eles na
  // lista de dependências, cada token do streaming no chat recriava as funções e
  // o efeito zerava o modal no meio do upload — e cancelava a ida ao chat.
  const fecharRef = useRef(onFechar)
  const importadoRef = useRef(onImportado)
  fecharRef.current = onFechar
  importadoRef.current = onImportado

  useEffect(() => {
    if (!aberto) return
    setArquivo(arquivoInicial)
    setErro(null)
    setPreview(null)
    setEnviando(false)

    function esc(e: KeyboardEvent) {
      if (e.key === 'Escape') fecharRef.current()
    }
    window.addEventListener('keydown', esc)
    return () => {
      window.removeEventListener('keydown', esc)
      // fechar durante a pausa do preview não pode disparar o turno no chat
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- arquivoInicial só vale na abertura
  }, [aberto])

  if (!aberto) return null

  function escolher(f: File | undefined) {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.xlsx')) {
      setErro('Envie o extrato em .xlsx — .xls e PDF não são aceitos.')
      return
    }
    setErro(null)
    setArquivo(f)
  }

  async function enviar() {
    if (!arquivo) return
    setEnviando(true)
    setErro(null)
    try {
      const p = await enviarExtrato(arquivo)
      setPreview(p)
      // Deixa o preview visível por um instante antes de levar ao chat.
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null
        fecharRef.current()
        importadoRef.current()
      }, 1100)
    } catch (e) {
      setErro((e as Error).message)
      setEnviando(false)
    }
  }

  const checagemFalhou = preview?.checagem_totais?.ok === false
  const ignoradas = preview?.linhas_ignoradas?.length ?? 0
  // Tolerante a preview antigo: sem os campos, nada disto aparece.
  const periodo = preview?.periodo ?? null
  const errosValidacao = preview?.validacao?.erros ?? []
  const avisosValidacao = preview?.validacao?.avisos ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onFechar()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Importar extrato do BTG"
        className="hairline fade-up w-full max-w-[560px] rounded-2xl bg-surface p-5 shadow-[0_24px_64px_rgba(0,0,0,0.6)]"
      >
        <div className="mb-1 flex items-start gap-3">
          <h2 className="flex-1 text-[16px] font-semibold">
            Importar extrato do BTG
          </h2>
          <button
            onClick={onFechar}
            className="rounded-md p-1 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
            aria-label="Fechar"
          >
            <X size={16} />
          </button>
        </div>

        <p className="mb-4 text-[13px] leading-relaxed text-ink-2">
          No app do BTG:{' '}
          <strong className="font-medium text-ink">
            Conta investimento → Extrato → exportar em XLSX
          </strong>
          . O arquivo fica em preparo no servidor e{' '}
          <strong className="font-medium text-ink">
            nada é gravado até você confirmar no chat
          </strong>
          .
        </p>

        {!preview && (
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
                escolher(e.dataTransfer.files[0])
              }}
              className={`flex w-full flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 transition-colors ${
                arrastando
                  ? 'border-accent bg-accent-soft/40'
                  : 'border-surface-3 bg-surface-2/50 hover:border-ink-3'
              }`}
            >
              {arquivo ? (
                <>
                  <FileSpreadsheet size={22} className="text-good" />
                  <span className="text-[13px] font-medium text-ink">
                    {arquivo.name}
                  </span>
                  <span className="text-[12px] text-ink-3">
                    {(arquivo.size / 1024).toFixed(0)} KB · clique para trocar
                  </span>
                </>
              ) : (
                <>
                  <Upload size={22} className="text-ink-3" />
                  <span className="text-[13px] text-ink-2">
                    Arraste o .xlsx aqui ou clique para escolher
                  </span>
                </>
              )}
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => escolher(e.target.files?.[0])}
            />
          </>
        )}

        {preview && (
          <div className="rounded-xl bg-surface-2 p-4">
            <div className="mb-3 flex items-baseline gap-2">
              <span className="text-[22px] font-semibold tabular-nums">
                {preview.total_posicoes}
              </span>
              <span className="text-[13px] text-ink-2">posições lidas</span>
              <span className="ml-auto text-[14px] font-medium tabular-nums">
                {fmtBRL(preview.total_valor_mercado)}
              </span>
            </div>
            <dl className="space-y-1 text-[12.5px] text-ink-2">
              <Linha
                rotulo="Data de referência"
                valor={fmtData(preview.data_referencia)}
              />
              {periodo && (
                <Linha
                  rotulo="Período"
                  valor={
                    <>
                      {periodo.inicio
                        ? `${fmtData(periodo.inicio)} — ${fmtData(periodo.fim)}`
                        : `até ${fmtData(periodo.fim)}`}
                      {!periodo.mensal && (
                        <span
                          className="ml-1.5 rounded bg-surface-3 px-1.5 py-0.5 text-[10.5px] font-medium text-warn"
                          title="Não é um mês inteiro: atualiza a carteira, mas não vira o mês na série de desempenho."
                        >
                          parcial
                        </span>
                      )}
                    </>
                  }
                />
              )}
              {preview.proventos_do_mes?.quantidade ? (
                <Linha
                  rotulo="Proventos no mês"
                  valor={fmtBRL(preview.proventos_do_mes.total_liquido)}
                />
              ) : null}
            </dl>

            {errosValidacao.length > 0 && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-surface p-2.5 text-[12.5px] text-critical">
                <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                <div className="min-w-0 space-y-1">
                  {errosValidacao.map((e) => (
                    <p key={e}>{e}</p>
                  ))}
                  <p className="font-medium">
                    Este extrato não será gravado enquanto houver erro de
                    conferência.
                  </p>
                </div>
              </div>
            )}

            {avisosValidacao.length > 0 && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-surface p-2.5 text-[12.5px] text-warn">
                <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                <div className="min-w-0 space-y-1">
                  {avisosValidacao.map((a) => (
                    <p key={a}>{a}</p>
                  ))}
                </div>
              </div>
            )}

            {(checagemFalhou || ignoradas > 0) && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-surface p-2.5 text-[12.5px] text-warn">
                <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                <span>
                  {checagemFalhou &&
                    (preview.checagem_totais?.aviso ??
                      'Os totais não bateram com o Sumário do extrato.')}
                  {checagemFalhou && ignoradas > 0 && ' '}
                  {ignoradas > 0 &&
                    `${ignoradas} linha(s) não interpretada(s).`}
                </span>
              </div>
            )}

            <p className="mt-3 text-[12px] text-ink-3">
              Levando ao chat para você conferir e confirmar…
            </p>
          </div>
        )}

        {erro && (
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-surface-2 p-2.5 text-[13px] text-critical">
            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
            <span>{erro}</span>
          </div>
        )}

        {!preview && (
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={onFechar}
              className="rounded-lg px-4 py-2 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
            >
              Cancelar
            </button>
            <button
              onClick={enviar}
              disabled={!arquivo || enviando}
              className="rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition-all enabled:hover:brightness-110 disabled:bg-surface-3 disabled:text-ink-3"
            >
              {enviando ? 'Lendo extrato…' : 'Enviar extrato'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function Linha({ rotulo, valor }: { rotulo: string; valor: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-ink-3">{rotulo}</dt>
      <dd className="tabular-nums">{valor}</dd>
    </div>
  )
}
