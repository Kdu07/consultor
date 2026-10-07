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

const BRL_SINAL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: 'exceptZero',
})

/** Resultado em reais, com sinal: "+R$ 259,70", "-R$ 12,00". */
export function fmtBRLSinal(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return BRL_SINAL.format(n)
}

export function fmtBRLCompacto(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return BRL_COMPACTO.format(n)
}

export function fmtPct(n: number | null | undefined, casas = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${n.toFixed(casas)}%`
}

const PCT_SINAL = new Map<number, Intl.NumberFormat>()

/**
 * Percentual em pontos (1.5 = 1,5%) no formato brasileiro, com sinal:
 * "+1,50%", "−1,20%". Para rentabilidade, onde o sinal é a informação.
 */
export function fmtPctSinal(n: number | null | undefined, casas = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  let f = PCT_SINAL.get(casas)
  if (!f) {
    f = new Intl.NumberFormat('pt-BR', {
      style: 'percent',
      minimumFractionDigits: casas,
      maximumFractionDigits: casas,
      signDisplay: 'exceptZero',
    })
    PCT_SINAL.set(casas, f)
  }
  return f.format(n / 100)
}

/** Percentual em pontos, formato brasileiro, sem sinal forçado: "***%". */
export function fmtPctBR(n: number | null | undefined, casas = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${n.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`
}

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const MESES_LONGOS = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
]

/** "2026-07" (ou "2026-07-31") → "jul/26". */
export function fmtMes(mes: string | null | undefined): string {
  if (!mes || mes.length < 7) return '—'
  return `${MESES[Number(mes.slice(5, 7)) - 1]}/${mes.slice(2, 4)}`
}

/** "2026-07" → "julho de 2026". */
export function fmtMesLongo(mes: string | null | undefined): string {
  if (!mes || mes.length < 7) return '—'
  return `${MESES_LONGOS[Number(mes.slice(5, 7)) - 1]} de ${mes.slice(0, 4)}`
}

/** Pontos percentuais, com sinal e vírgula decimal: "+1,5 p.p.", "-0,3 p.p.". */
export function fmtPP(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const texto = n.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return `${n > 0 ? '+' : ''}${texto} p.p.`
}

/** Quantidade: inteira com milhar ("1.000"), fracionária com até 4 casas ("5,69"). */
export function fmtQtde(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString('pt-BR', { maximumFractionDigits: 4 })
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
