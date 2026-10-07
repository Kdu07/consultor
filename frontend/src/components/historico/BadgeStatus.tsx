import { CircleAlert, CircleCheck, CircleDashed, CircleHelp, CircleMinus } from 'lucide-react'
import type { StatusMes } from '../../lib/api'

/**
 * Status de um mês. Ícone + rótulo sempre — a cor nunca carrega o significado
 * sozinha (regra dos status no método de dataviz).
 */
const STATUS: Record<
  StatusMes,
  { rotulo: string; Icone: typeof CircleCheck; cor: string; dica: string }
> = {
  ok: {
    rotulo: 'ok',
    Icone: CircleCheck,
    cor: 'text-good',
    dica: 'Aportes e resgates conferidos no razão da conta.',
  },
  provisorio: {
    rotulo: 'provisório',
    Icone: CircleHelp,
    cor: 'text-warn',
    dica: 'Há lançamentos da conta sem classificação, ou o razão não fecha. O número pode mudar.',
  },
  sem_lancamentos: {
    rotulo: 'sem razão',
    Icone: CircleAlert,
    cor: 'text-serious',
    dica: 'Arquivo antigo, sem os lançamentos da conta: reenvie o XLSX para calcular a rentabilidade.',
  },
  sem_base: {
    rotulo: 'sem base',
    Icone: CircleMinus,
    cor: 'text-ink-3',
    dica: 'Sem patrimônio no início do mês (primeiro mês da conta).',
  },
  periodo_parcial: {
    rotulo: 'parcial',
    Icone: CircleDashed,
    cor: 'text-ink-3',
    dica: 'O extrato não cobre o mês inteiro.',
  },
  lacuna: {
    rotulo: 'sem extrato',
    Icone: CircleDashed,
    cor: 'text-ink-3',
    dica: 'Nenhum extrato arquivado para este mês.',
  },
}

export default function BadgeStatus({ status }: { status: StatusMes | null | undefined }) {
  const s = STATUS[status ?? 'lacuna'] ?? STATUS.lacuna
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] whitespace-nowrap ${s.cor}`}
      title={s.dica}
    >
      <s.Icone size={12} className="shrink-0" aria-hidden="true" />
      <span className="text-ink-2">{s.rotulo}</span>
    </span>
  )
}

export function dicaDoStatus(status: StatusMes | null | undefined): string {
  return (STATUS[status ?? 'lacuna'] ?? STATUS.lacuna).dica
}
