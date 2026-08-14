const BRL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const BRL_COMPACTO = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 1,
})

export function fmtBRL(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return BRL.format(n)
}

export function fmtBRLCompacto(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return BRL_COMPACTO.format(n)
}

export function fmtPct(n: number | null | undefined, casas = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${n.toFixed(casas)}%`
}

export function fmtPP(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${n > 0 ? '+' : ''}${n.toFixed(1)} p.p.`
}

export function fmtQtde(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  if (Number.isInteger(n)) return n.toLocaleString('pt-BR')
  return n.toFixed(4).replace(/\.?0+$/, '')
}

/** ISO → "10/08/2026 14:32". Aceita data pura ("2026-08-10") sem virar D-1. */
export function fmtDataHora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = parseISO(iso)
  if (!d) return '—'
  return `${d.toLocaleDateString('pt-BR')} ${d.toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
}

export function fmtData(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = parseISO(iso)
  return d ? d.toLocaleDateString('pt-BR') : '—'
}

export function fmtDataCurta(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = parseISO(iso)
  return d
    ? d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })
    : '—'
}

export function fmtHora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = parseISO(iso)
  return d
    ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : '—'
}

function parseISO(iso: string): Date | null {
  // Duas armadilhas opostas do construtor Date:
  //
  // "2026-08-10" (data pura) é lido como UTC e retrocede um dia em fusos
  // negativos — forçamos meia-noite local.
  //
  // "2026-08-10T22:30:00" (sem offset) é lido como hora LOCAL, mas o backend
  // grava tudo em UTC e o SQLite devolve datetime naive, sem o sufixo: sem o
  // "Z" o horário apareceria 3h adiantado, virando o dia perto da meia-noite.
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const d = new Date(`${iso}T00:00:00`)
    return Number.isNaN(d.getTime()) ? null : d
  }

  const temFuso = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  const d = new Date(temFuso ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}
