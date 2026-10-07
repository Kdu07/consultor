import { useState, type ReactNode } from 'react'
import { escala, rotulosVisiveis, ticks, useLargura } from '../../lib/graficos'

interface Props {
  titulo: string
  rotulos: string[]
  /** Um valor por posição; null = sem dado (sem coluna). Negativo desce da base. */
  valores: (number | null)[]
  /** Cor da série única — o título do card nomeia o que é mostrado. */
  cor: string
  formatarValor(v: number): string
  formatarEixo(v: number): string
  rotuloTooltip?(i: number): string
  /** Linhas extras do tooltip naquela posição. */
  detalheTooltip?(i: number): ReactNode
  altura?: number
}

const M = { esq: 58, dir: 14, topo: 8, base: 26 }
const RAIO = 4
const LARGURA_MAX = 24

/**
 * Colunas de uma série só, crescendo de uma base única. Ponta de 4px
 * arredondada, base reta; nunca mais que 24px de largura — o resto da faixa é
 * respiro. Cada coluna é o próprio alvo do ponteiro (a faixa inteira, não só os
 * pixels pintados) e se destaca ao ser apontada.
 */
export default function GraficoColunas({
  titulo,
  rotulos,
  valores,
  cor,
  formatarValor,
  formatarEixo,
  rotuloTooltip,
  detalheTooltip,
  altura = 120,
}: Props) {
  const [ref, largura] = useLargura<HTMLDivElement>()
  const [ativo, setAtivo] = useState<number | null>(null)

  const n = rotulos.length
  const presentes = valores.filter((v): v is number => v !== null)
  const marcas = ticks(Math.min(0, ...presentes), Math.max(0, ...presentes), 3)
  const larguraPlot = Math.max(largura - M.esq - M.dir, 10)
  const faixa = larguraPlot / Math.max(n, 1)
  const barra = Math.min(LARGURA_MAX, faixa * 0.62)
  const centro = (i: number) => M.esq + faixa * (i + 0.5)
  const y = escala(marcas[0], marcas[marcas.length - 1], M.topo + altura, M.topo)
  const base = y(0)
  const visiveis = largura > 0 ? rotulosVisiveis(n, larguraPlot + 30) : []

  function coluna(i: number, v: number): string {
    const x0 = centro(i) - barra / 2
    const x1 = centro(i) + barra / 2
    const topo = y(v)
    const h = Math.abs(base - topo)
    const r = Math.min(RAIO, h, barra / 2)
    if (v >= 0) {
      return `M${x0},${base}L${x0},${topo + r}Q${x0},${topo} ${x0 + r},${topo}L${x1 - r},${topo}Q${x1},${topo} ${x1},${topo + r}L${x1},${base}Z`
    }
    return `M${x0},${base}L${x0},${topo - r}Q${x0},${topo} ${x0 + r},${topo}L${x1 - r},${topo}Q${x1},${topo} ${x1},${topo - r}L${x1},${base}Z`
  }

  function teclar(e: React.KeyboardEvent) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      const delta = e.key === 'ArrowLeft' ? -1 : 1
      setAtivo((a) => (a === null ? n - 1 : Math.max(0, Math.min(n - 1, a + delta))))
    } else if (e.key === 'Escape') {
      setAtivo(null)
    }
  }

  const tooltipEsquerda =
    ativo === null ? 0 : Math.min(Math.max(centro(ativo), 90), Math.max(largura - 90, 90))

  return (
    <div
      ref={ref}
      className="relative outline-none"
      tabIndex={0}
      role="group"
      aria-label={`${titulo}. Use as setas para percorrer os meses.`}
      onKeyDown={teclar}
      onFocus={() => setAtivo((a) => a ?? n - 1)}
      onBlur={() => setAtivo(null)}
    >
      {largura > 0 && (
        <svg
          width={largura}
          height={M.topo + altura + M.base}
          className="block touch-none"
          onPointerLeave={() => setAtivo(null)}
          aria-hidden="true"
        >
          {marcas.map((m) => (
            <g key={m}>
              <line
                x1={M.esq}
                x2={M.esq + larguraPlot}
                y1={y(m)}
                y2={y(m)}
                stroke={m === 0 ? 'var(--color-baseline)' : 'var(--color-line)'}
                strokeWidth={1}
              />
              <text
                x={M.esq - 8}
                y={y(m)}
                dy="0.32em"
                textAnchor="end"
                className="fill-ink-3 text-[10.5px] tabular-nums"
              >
                {formatarEixo(m)}
              </text>
            </g>
          ))}

          {valores.map((v, i) =>
            v === null || v === 0 ? null : (
              <path
                key={i}
                d={coluna(i, v)}
                fill={cor}
                style={ativo === i ? { filter: 'brightness(1.35)' } : undefined}
              />
            ),
          )}

          {/* alvo do ponteiro: a faixa inteira de cada mês */}
          {rotulos.map((_, i) => (
            <rect
              key={`h${i}`}
              x={M.esq + faixa * i}
              y={M.topo}
              width={faixa}
              height={altura}
              fill="transparent"
              onPointerEnter={() => setAtivo(i)}
              onPointerDown={() => setAtivo(i)}
            />
          ))}

          {visiveis.map((i) => (
            <text
              key={`x${i}`}
              x={centro(i)}
              y={M.topo + altura + 17}
              textAnchor="middle"
              className="fill-ink-3 text-[10.5px]"
            >
              {rotulos[i]}
            </text>
          ))}
        </svg>
      )}

      {ativo !== null && largura > 0 && (
        <div
          className="hairline pointer-events-none absolute z-10 min-w-[140px] -translate-x-1/2 rounded-lg bg-surface-2 px-3 py-2 text-[12px] shadow-lg"
          style={{ left: tooltipEsquerda, top: 0 }}
        >
          <div className="mb-0.5 text-[11px] text-ink-3">
            {rotuloTooltip ? rotuloTooltip(ativo) : rotulos[ativo]}
          </div>
          <div className="font-semibold tabular-nums text-ink">
            {valores[ativo] === null ? 'Sem dado' : formatarValor(valores[ativo]!)}
          </div>
          {detalheTooltip?.(ativo)}
        </div>
      )}
    </div>
  )
}
