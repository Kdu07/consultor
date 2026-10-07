import { useLayoutEffect, useRef, useState } from 'react'

/**
 * Peças dos gráficos em SVG próprio (docs/PLANO_HISTORICO.md, Bloco 7): sem
 * biblioteca de gráficos. O SVG é desenhado em pixels reais — a largura vem do
 * contêiner via ResizeObserver —, nada de viewBox esticado: assim marcador
 * continua redondo e linha continua com 2px em qualquer largura.
 */

/** Largura atual do elemento (0 até o primeiro layout). */
export function useLargura<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [largura, setLargura] = useState(0)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setLargura(el.clientWidth)
    const obs = new ResizeObserver((entradas) => {
      const w = entradas[0]?.contentRect.width ?? 0
      setLargura(Math.round(w))
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  return [ref, largura] as const
}

/** Escala linear: domínio → faixa em pixels. */
export function escala(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0 || 1
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0)
}

/**
 * Marcas "bonitas" do eixo (1, 2, 2,5, 5 × 10ⁿ) cobrindo [min, max]. Devolve o
 * domínio já arredondado para as marcas das pontas.
 */
export function ticks(min: number, max: number, alvo = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0]
  if (min === max) {
    const folga = Math.abs(min) * 0.1 || 1
    min -= folga
    max += folga
  }
  const bruto = (max - min) / Math.max(alvo, 1)
  const potencia = 10 ** Math.floor(Math.log10(bruto))
  const passo =
    [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto) ?? 10 * potencia
  const inicio = Math.floor(min / passo) * passo
  const fim = Math.ceil(max / passo) * passo
  const out: number[] = []
  for (let v = inicio; v <= fim + passo / 2; v += passo) {
    out.push(Math.abs(v) < passo / 1e6 ? 0 : Number(v.toFixed(10)))
  }
  return out
}

/** Índices dos rótulos do eixo X que cabem sem encostar (sempre o último). */
export function rotulosVisiveis(n: number, largura: number, larguraRotulo = 44): number[] {
  if (n <= 0) return []
  const cabem = Math.max(1, Math.floor(largura / larguraRotulo))
  const passo = Math.max(1, Math.ceil(n / cabem))
  const out: number[] = []
  for (let i = n - 1; i >= 0; i -= passo) out.unshift(i)
  return out
}

/** "2026-01".."2026-04" → todos os meses entre os dois, inclusive. */
export function mesesEntre(de: string, ate: string): string[] {
  const out: string[] = []
  let ano = Number(de.slice(0, 4))
  let mes = Number(de.slice(5, 7))
  const fimAno = Number(ate.slice(0, 4))
  const fimMes = Number(ate.slice(5, 7))
  while (ano < fimAno || (ano === fimAno && mes <= fimMes)) {
    out.push(`${ano}-${String(mes).padStart(2, '0')}`)
    mes += 1
    if (mes > 12) {
      mes = 1
      ano += 1
    }
  }
  return out
}

/** "2026-01" → "2025-12". */
export function mesAnterior(mes: string): string {
  let ano = Number(mes.slice(0, 4))
  let m = Number(mes.slice(5, 7)) - 1
  if (m === 0) {
    m = 12
    ano -= 1
  }
  return `${ano}-${String(m).padStart(2, '0')}`
}
