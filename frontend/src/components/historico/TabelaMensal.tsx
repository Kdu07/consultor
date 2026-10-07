import { Info } from 'lucide-react'
import type { MesDesempenho } from '../../lib/api'
import { fmtBRL, fmtMes, fmtPctBR, fmtPctSinal } from '../../lib/format'
import BadgeStatus from './BadgeStatus'

const AVISOS: Record<string, string> = {
  continuidade:
    'O patrimônio no início do mês não bate com o fechamento do mês anterior — vale o do próprio extrato.',
  fluxo_relevante:
    'Aportes e resgates acima de 10% do patrimônio: a rentabilidade do mês é uma aproximação.',
  transferencia_de_ativos:
    'Ativos trazidos ou levados de outra corretora contaram como aporte ou resgate.',
}

/**
 * Mês a mês, do mais recente ao mais antigo. É também a versão em tabela dos
 * gráficos acima: todo valor que um tooltip mostra está aqui, sem precisar
 * apontar para nada.
 */
export default function TabelaMensal({ meses }: { meses: MesDesempenho[] }) {
  const linhas = [...meses].reverse()

  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
            <Th>Mês</Th>
            <Th>Status</Th>
            <Th direita>Patrimônio</Th>
            <Th direita>Aportes líq.</Th>
            <Th direita>Ganho</Th>
            <Th direita>Rent.</Th>
            <Th direita>CDI</Th>
            <Th direita>% do CDI</Th>
            <Th direita>IPCA</Th>
            <Th direita>Real</Th>
            <Th direita>Proventos</Th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {linhas.map((m) => (
            <tr key={m.mes} className="border-t border-line transition-colors hover:bg-surface-2/60">
              <td className="px-4 py-2 font-medium text-ink">{fmtMes(m.mes)}</td>
              <td className="px-4 py-2">
                <span className="inline-flex items-center gap-1.5">
                  <BadgeStatus status={m.status} />
                  {m.avisos.length > 0 && (
                    <span title={m.avisos.map((a) => AVISOS[a] ?? a).join(' ')} className="text-ink-3">
                      <Info size={12} aria-label={m.avisos.map((a) => AVISOS[a] ?? a).join(' ')} />
                    </span>
                  )}
                </span>
              </td>
              <Td>{fmtBRL(m.patrimonio_fim)}</Td>
              <Td>{m.status === 'ok' || m.status === 'provisorio' ? fmtBRL(m.aportes_liquidos) : '—'}</Td>
              <Td>{fmtBRL(m.ganho)}</Td>
              <Td forte>{fmtPctSinal(m.rentabilidade_pct)}</Td>
              <Td>{fmtPctSinal(m.cdi_pct)}</Td>
              <Td>{fmtPctBR(m.pct_do_cdi, 0)}</Td>
              <Td>{fmtPctSinal(m.ipca_pct)}</Td>
              <Td>{fmtPctSinal(m.retorno_real_pct)}</Td>
              <Td>{m.proventos ? fmtBRL(m.proventos.total) : '—'}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Th({ children, direita }: { children: React.ReactNode; direita?: boolean }) {
  return (
    <th className={`px-4 pb-2 font-semibold whitespace-nowrap ${direita ? 'text-right' : 'text-left'}`}>
      {children}
    </th>
  )
}

function Td({ children, forte }: { children: React.ReactNode; forte?: boolean }) {
  return (
    <td className={`px-4 py-2 text-right whitespace-nowrap ${forte ? 'font-medium text-ink' : 'text-ink-2'}`}>
      {children}
    </td>
  )
}
