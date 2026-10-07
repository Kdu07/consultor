import { useState } from 'react'
import { escala, rotulosVisiveis, ticks, useLargura } from '../../lib/graficos'

export interface SerieLinha {
  id: string
  rotulo: string
  /** Cor da marca (nunca do texto — o texto usa as tintas do tema). */
  cor: string
  /** Segunda codificação além da cor: tracejado. */
  tracejado?: boolean
  /** A série que é o assunto: desenhada por cima e com o ponto final marcado. */
  destaque?: boolean
  /** Um valor por posição de `rotulos`; null = sem dado (a linha se interrompe). */
  valores: (number | null)[]
}

interface Props {
  /** Nome do gráfico para leitor de tela. */
  titulo: string
  rotulos: string[]
  series: SerieLinha[]
  formatarValor(v: number): string
  formatarEixo(v: number): string
  /** Cabeçalho do tooltip em cada posição (padrão: o rótulo do eixo). */
  rotuloTooltip?(i: number): string
  /** Posições sem dado da carteira, sombreadas atrás das linhas. */
  vazias?: number[]
  /** Inclui o zero no eixo e desenha a linha de base mais forte. */
  comZero?: boolean
  altura?: number
}

const M = { esq: 58, dir: 14, topo: 10, base: 26 }

/**
 * Linhas em SVG próprio: 2px, junções redondas, grade em fio sólido, eixo único.
 * A cruz de leitura acha o mês mais próximo — o leitor mira uma data, não uma
 * linha de 2px — e o tooltip lista todas as séries naquele mês. Teclado: as
 * setas andam pelos meses, Esc sai.
 */
export default function GraficoLinhas({
  titulo,
  rotulos,
  series,
  formatarValor,
  formatarEixo,
  rotuloTooltip,
  vazias = [],
  comZero = false,
  altura = 200,
}: Props) {
  const [ref, largura] = useLargura<HTMLDivElement>()
  const [ativo, setAtivo] = useState<number | null>(null)

  const n = rotulos.length
  const valores = series.flatMap((s) => s.valores.filter((v): v is number => v !== null))
  if (comZero) valores.push(0)
  const marcas = ticks(Math.min(...valores), Math.max(...valores), 4)
  const y0 = marcas[0]
  const y1 = marcas[marcas.length - 1]

  const larguraPlot = Math.max(largura - M.esq - M.dir, 10)
  const passo = n > 1 ? larguraPlot / (n - 1) : larguraPlot
  const x = (i: number) => (n > 1 ? M.esq + i * passo : M.esq + larguraPlot / 2)
  const y = escala(y0, y1, M.topo + altura, M.topo)
  const alturaTotal = M.topo + altura + M.base

  function caminho(vals: (number | null)[]): { d: string; soltos: number[] } {
    let d = ''
    const soltos: number[] = []
    let i = 0
    while (i < vals.length) {
      if (vals[i] === null) {
        i += 1
        continue
      }
      const inicio = i
      while (i + 1 < vals.length && vals[i + 1] !== null) i += 1
      if (i === inicio) soltos.push(inicio)
      else {
        d += `M${x(inicio)},${y(vals[inicio]!)}`
        for (let k = inicio + 1; k <= i; k += 1) d += `L${x(k)},${y(vals[k]!)}`
      }
      i += 1
    }
    return { d, soltos }
  }

  function apontar(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - r.left
    const i = n > 1 ? Math.round((px - M.esq) / passo) : 0
    setAtivo(Math.max(0, Math.min(n - 1, i)))
  }

  function teclar(e: React.KeyboardEvent) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      const delta = e.key === 'ArrowLeft' ? -1 : 1
      setAtivo((a) => Math.max(0, Math.min(n - 1, (a ?? n - 1) + (a === null ? 0 : delta))))
    } else if (e.key === 'Escape') {
      setAtivo(null)
    }
  }

  const ultimoValor = (s: SerieLinha) => {
    for (let i = s.valores.length - 1; i >= 0; i -= 1) {
      if (s.valores[i] !== null) return { i, v: s.valores[i]! }
    }
    return null
  }

  const ordenadas = [...series].sort((a, b) => Number(!!a.destaque) - Number(!!b.destaque))
  const visiveis = largura > 0 ? rotulosVisiveis(n, larguraPlot + 30) : []
  const tooltipEsquerda =
    ativo === null ? 0 : Math.min(Math.max(x(ativo), 90), Math.max(largura - 90, 90))

  return (
    <div>
      {series.length >= 2 && (
        <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          {series.map((s) => {
            const fim = ultimoValor(s)
            return (
              <li key={s.id} className="flex items-center gap-1.5">
                <ChaveLinha cor={s.cor} tracejado={s.tracejado} />
                <span className="text-ink-2">{s.rotulo}</span>
                {fim && (
                  <span className={`tabular-nums ${s.destaque ? 'font-semibold text-ink' : 'text-ink-2'}`}>
                    {formatarValor(fim.v)}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}

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
            height={alturaTotal}
            className="block touch-none"
            onPointerMove={apontar}
            onPointerDown={apontar}
            onPointerLeave={() => setAtivo(null)}
            aria-hidden="true"
          >
            {vazias.map((i) => (
              <rect
                key={`v${i}`}
                x={x(i) - (n > 1 ? passo / 2 : larguraPlot / 2)}
                y={M.topo}
                width={n > 1 ? passo : larguraPlot}
                height={altura}
                fill="var(--color-surface-2)"
              />
            ))}

            {marcas.map((m) => (
              <g key={m}>
                <line
                  x1={M.esq}
                  x2={M.esq + larguraPlot}
                  y1={y(m)}
                  y2={y(m)}
                  stroke={comZero && m === 0 ? 'var(--color-baseline)' : 'var(--color-line)'}
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

            {visiveis.map((i) => (
              <text
                key={`x${i}`}
                x={x(i)}
                y={M.topo + altura + 17}
                textAnchor={n > 1 && i === 0 ? 'start' : n > 1 && i === n - 1 ? 'end' : 'middle'}
                className="fill-ink-3 text-[10.5px]"
              >
                {rotulos[i]}
              </text>
            ))}

            {ordenadas.map((s) => {
              const { d, soltos } = caminho(s.valores)
              return (
                <g key={s.id}>
                  {d && (
                    <path
                      d={d}
                      fill="none"
                      stroke={s.cor}
                      strokeWidth={2}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      strokeDasharray={s.tracejado ? '5 4' : undefined}
                    />
                  )}
                  {soltos.map((i) => (
                    <circle key={i} cx={x(i)} cy={y(s.valores[i]!)} r={3} fill={s.cor} />
                  ))}
                </g>
              )
            })}

            {ordenadas
              .filter((s) => s.destaque)
              .map((s) => {
                const fim = ultimoValor(s)
                return fim ? (
                  <circle
                    key={`fim-${s.id}`}
                    cx={x(fim.i)}
                    cy={y(fim.v)}
                    r={4}
                    fill={s.cor}
                    stroke="var(--color-surface)"
                    strokeWidth={2}
                  />
                ) : null
              })}

            {ativo !== null && (
              <g>
                <line
                  x1={x(ativo)}
                  x2={x(ativo)}
                  y1={M.topo}
                  y2={M.topo + altura}
                  stroke="var(--color-baseline)"
                  strokeWidth={1}
                />
                {ordenadas.map((s) =>
                  s.valores[ativo] === null ? null : (
                    <circle
                      key={`a-${s.id}`}
                      cx={x(ativo)}
                      cy={y(s.valores[ativo]!)}
                      r={4}
                      fill={s.cor}
                      stroke="var(--color-surface)"
                      strokeWidth={2}
                    />
                  ),
                )}
              </g>
            )}
          </svg>
        )}

        {ativo !== null && largura > 0 && (
          <div
            className="hairline pointer-events-none absolute z-10 min-w-[150px] -translate-x-1/2 rounded-lg bg-surface-2 px-3 py-2 text-[12px] shadow-lg"
            style={{ left: tooltipEsquerda, top: 0 }}
          >
            <div className="mb-1 text-[11px] text-ink-3">
              {rotuloTooltip ? rotuloTooltip(ativo) : rotulos[ativo]}
            </div>
            {series.map((s) => (
              <div key={s.id} className="flex items-center gap-2">
                <ChaveLinha cor={s.cor} tracejado={s.tracejado} />
                <span className="font-semibold tabular-nums text-ink">
                  {s.valores[ativo] === null ? '—' : formatarValor(s.valores[ativo]!)}
                </span>
                <span className="text-ink-3">{s.rotulo}</span>
              </div>
            ))}
            {vazias.includes(ativo) && (
              <div className="mt-1 text-[11px] text-ink-3">Sem rentabilidade neste mês</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** A chave de uma linha: um traço curto da cor da série, não um quadrado. */
export function ChaveLinha({ cor, tracejado }: { cor: string; tracejado?: boolean }) {
  return (
    <svg width="16" height="6" aria-hidden="true" className="shrink-0">
      <line
        x1="1"
        x2="15"
        y1="3"
        y2="3"
        stroke={cor}
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={tracejado ? '4 3' : undefined}
      />
    </svg>
  )
}
