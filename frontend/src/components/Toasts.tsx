import { createContext, useCallback, useContext, useState } from 'react'
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react'

type Tipo = 'ok' | 'erro' | 'info'

interface Toast {
  id: number
  tipo: Tipo
  texto: string
}

const Ctx = createContext<(tipo: Tipo, texto: string) => void>(() => {})

export const useToast = () => useContext(Ctx)

const ICONE = { ok: CircleCheck, erro: CircleAlert, info: Info }
// Status sempre com ícone + texto — a cor nunca carrega o significado sozinha.
const COR = {
  ok: 'text-good',
  erro: 'text-critical',
  info: 'text-ink-2',
} as const

export function ProvedorToasts({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const mostrar = useCallback((tipo: Tipo, texto: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tipo, texto }])
    setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id))
    }, 5000)
  }, [])

  return (
    <Ctx.Provider value={mostrar}>
      {children}
      <div className="pointer-events-none fixed bottom-5 left-1/2 z-100 flex w-[min(420px,92vw)] -translate-x-1/2 flex-col gap-2">
        {toasts.map((t) => {
          const Icone = ICONE[t.tipo]
          return (
            <div
              key={t.id}
              role="status"
              className="hairline fade-up pointer-events-auto flex items-start gap-2.5 rounded-xl bg-surface-2 px-3.5 py-3 shadow-[0_16px_48px_rgba(0,0,0,0.5)]"
            >
              <Icone size={16} className={`mt-0.5 shrink-0 ${COR[t.tipo]}`} />
              <span className="flex-1 text-[13px] leading-snug text-ink">
                {t.texto}
              </span>
              <button
                onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}
                className="shrink-0 text-ink-3 transition-colors hover:text-ink"
                aria-label="Fechar"
              >
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
    </Ctx.Provider>
  )
}
