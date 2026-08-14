import { useEffect, useRef } from 'react'
import { ArrowUp, Paperclip, Square } from 'lucide-react'

interface Props {
  valor: string
  onChange(v: string): void
  onEnviar(): void
  onParar(): void
  onAnexar(): void
  ocupado: boolean
}

const ALTURA_MAX = 200

export default function Composer({
  valor,
  onChange,
  onEnviar,
  onParar,
  onAnexar,
  ocupado,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // Auto-resize: zera a altura antes de medir para o campo também encolher.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, ALTURA_MAX)}px`
  }, [valor])

  useEffect(() => {
    function atalho(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        ref.current?.focus()
      }
    }
    window.addEventListener('keydown', atalho)
    return () => window.removeEventListener('keydown', atalho)
  }, [])

  function teclado(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!ocupado) onEnviar()
    }
  }

  const podeEnviar = valor.trim().length > 0 && !ocupado

  return (
    <div className="relative shrink-0 px-4 pb-4">
      {/* o texto do chat some suavemente atrás do composer ao rolar */}
      <div className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-gradient-to-t from-plane to-transparent" />

      <div className="mx-auto w-full max-w-[760px]">
        <div className="hairline flex items-end gap-2 rounded-[24px] bg-surface p-2 shadow-[0_2px_16px_rgba(0,0,0,0.3)] transition-colors focus-within:border-accent/50">
          <button
            onClick={onAnexar}
            title="Importar extrato do BTG (.xlsx)"
            className="flex size-9 shrink-0 items-center justify-center rounded-full text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink-2"
          >
            <Paperclip size={17} />
          </button>

          <textarea
            ref={ref}
            rows={1}
            value={valor}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={teclado}
            placeholder="Pergunte sobre sua carteira…"
            className="max-h-[200px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-relaxed text-ink outline-none placeholder:text-ink-3"
          />

          {ocupado ? (
            <button
              onClick={onParar}
              title="Parar"
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-3 text-ink transition-colors hover:bg-surface-2"
            >
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={onEnviar}
              disabled={!podeEnviar}
              title="Enviar (Enter)"
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent text-white transition-all enabled:hover:brightness-110 disabled:bg-surface-3 disabled:text-ink-3"
            >
              <ArrowUp size={17} strokeWidth={2.5} />
            </button>
          )}
        </div>

        <p className="mt-2 text-center text-[11px] text-ink-3">
          O consultor é educativo e não executa ordens. Confira os números antes
          de decidir.
        </p>
      </div>
    </div>
  )
}
