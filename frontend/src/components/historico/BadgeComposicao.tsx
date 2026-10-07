import { CircleAlert, CircleCheck, CircleDashed, CircleHelp, CircleMinus } from 'lucide-react'
import type { StatusComposicao } from '../../lib/api'

/**
 * Status de um papel ou de uma classe na composição. Como no BadgeStatus:
 * ícone + rótulo sempre, a cor nunca carrega o significado sozinha.
 */
const STATUS: Record<
  StatusComposicao,
  { rotulo: string; Icone: typeof CircleCheck; cor: string; dica: string }
> = {
  ok: {
    rotulo: 'ok',
    Icone: CircleCheck,
    cor: 'text-good',
    dica: 'Compras, vendas e renda conferidas nos extratos.',
  },
  estimado: {
    rotulo: 'estimado',
    Icone: CircleHelp,
    cor: 'text-warn',
    dica:
      'Um resgate de título não apareceu com valor no razão: foi estimado pela quantidade que saiu × o preço médio dos dois fechamentos.',
  },
  parcial: {
    rotulo: 'parcial',
    Icone: CircleDashed,
    cor: 'text-ink-3',
    dica: 'Algum mês do período ficou sem número (sem o extrato do mês anterior, por exemplo).',
  },
  pendente: {
    rotulo: 'pendente',
    Icone: CircleAlert,
    cor: 'text-serious',
    dica: 'A quantidade mudou sem compra ou venda no extrato: diga o que houve para o resultado entrar.',
  },
  sem_base: {
    rotulo: 'sem base',
    Icone: CircleMinus,
    cor: 'text-ink-3',
    dica: 'Sem o extrato do mês anterior, não há de onde medir.',
  },
  indisponivel: {
    rotulo: 'sem número',
    Icone: CircleMinus,
    cor: 'text-ink-3',
    dica:
      'Não deu para calcular: arquivo antigo, sem os lotes de renda fixa (reenvie o XLSX), ou evento sem preço comparável.',
  },
}

export default function BadgeComposicao({ status }: { status: StatusComposicao }) {
  const s = STATUS[status] ?? STATUS.indisponivel
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
