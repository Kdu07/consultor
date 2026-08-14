import { useRef, useState } from 'react'
import { fmtBRL, fmtData } from '../../lib/format'

export interface PontoSerie {
  rotulo: string
  valor: number
}

const L = 260 // largura do viewBox (o SVG escala; a linha usa non-scaling-stroke)
const A = 56
const PAD = 3

/**
 * Série única de patrimônio ao longo dos snapshots. Uma série só → sem legenda,
 * o título do card já nomeia o que está sendo mostrado. Traz crosshair +
 * tooltip, como toda linha interativa.
 */
export default function Sparkline({ pontos }: { pontos: PontoSerie[] }) {
  const [ativo, setAtivo] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  if (pontos.length < 2) {
    return (
      <p className="py-3 text-[12px] text-ink-3">
        Um snapshot só até agora — a linha aparece a partir do segundo.
      </p>
    )
  }

  const valores = pontos.map((p) => p.valor)
  const min = Math.min(...valores)
  const max = Math.max(...valores)
  const span = max - min || Math.abs(max) || 1

  const x = (i: number) => PAD + (i / (pontos.length - 1)) * (L - PAD * 2)
  const y = (v: number) => A - PAD - ((v - min) / span) * (A - PAD * 2)

  const linha = pontos.map((p, i) => `${x(i)},${y(p.valor)}`).join(' ')
  const area = `${x(0)},${A} ${linha} ${x(pontos.length - 1)},${A}`

  const subiu = valores[valores.length - 1] >= valores[0]
  const cor = subiu ? 'var(--color-good)' : 'var(--color-critical)'

  function mover(e: React.MouseEvent<SVGSVGElement>) {
    const r = svgRef.current?.getBoundingClientRect()
    if (!r || r.width === 0) return
    const frac = (e.clientX - r.left) / r.width
    const i = Math.round(frac * (pontos.length - 1))
    setAtivo(Math.max(0, Math.min(pontos.length - 1, i)))
  }

  const p = ativo !== null ? pontos[ativo] : null

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${L} ${A}`}
        preserveAspectRatio="none"
        className="h-14 w-full cursor-crosshair"
        onMouseMove={mover}
        onMouseLeave={() => setAtivo(null)}
        role="img"
        aria-label={`Patrimônio em ${pontos.length} snapshots, de ${fmtBRL(valores[0])} a ${fmtBRL(valores[valores.length - 1])}`}
      >
        <defs>
          <linearGradient id="grad-spark" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={cor} stopOpacity="0.22" />
            <stop offset="100%" stopColor={cor} stopOpacity="0" />
          </linearGradient>
        </defs>

        <polygon points={area} fill="url(#grad-spark)" />
        <polyline
          points={linha}
          fill="none"
          stroke={cor}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {ativo !== null && (
          <>
            <line
              x1={x(ativo)}
              y1={0}
              x2={x(ativo)}
              y2={A}
              stroke="var(--color-baseline)"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={x(ativo)}
              cy={y(pontos[ativo].valor)}
              r="3.5"
              fill={cor}
              stroke="var(--color-surface)"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}
      </svg>

      {p && (
        <div
          className="hairline pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full rounded-lg bg-surface-2 px-2.5 py-1.5 text-[12px] whitespace-nowrap shadow-lg"
          style={{ left: `${(ativo! / (pontos.length - 1)) * 100}%` }}
        >
          <div className="font-medium tabular-nums">{fmtBRL(p.valor)}</div>
          <div className="text-[11px] text-ink-3">{fmtData(p.rotulo)}</div>
        </div>
      )}
    </div>
  )
}
