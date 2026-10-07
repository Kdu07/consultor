import { TriangleAlert } from 'lucide-react'
import type { Desempenho } from '../../lib/api'
import { fmtBRL, fmtMes } from '../../lib/format'

interface Props {
  pendencias: Desempenho['pendencias']
  onIrExtratos(): void
}

/**
 * O que impede a rentabilidade de ser definitiva, numa frase por motivo, com o
 * caminho para resolver. Some quando não há nada pendente.
 */
export default function BannerPendencias({ pendencias, onIrExtratos }: Props) {
  const itens: string[] = []
  if (pendencias.nao_classificados > 0) {
    itens.push(
      `${pendencias.nao_classificados} lançamento(s) da conta sem classificação ` +
        `(${fmtBRL(pendencias.valor_nao_classificado)} no total) — os meses afetados ficam provisórios.`,
    )
  }
  if (pendencias.meses_sem_lancamentos.length > 0) {
    itens.push(
      `Arquivos antigos, sem os lançamentos da conta: ${lista(pendencias.meses_sem_lancamentos)}. ` +
        'Reenvie esses XLSX para calcular a rentabilidade.',
    )
  }
  if (pendencias.meses_razao_nao_fecha.length > 0) {
    itens.push(
      `O razão da conta não fecha em ${lista(pendencias.meses_razao_nao_fecha)} — confira os lançamentos.`,
    )
  }
  if (pendencias.meses_faltantes.length > 0) {
    itens.push(`Sem extrato arquivado em ${lista(pendencias.meses_faltantes)}.`)
  }
  // Quebras de encadeamento: o backend já manda a frase pronta, com os meses e a diferença.
  for (const quebra of pendencias.quebras_continuidade ?? []) {
    itens.push(`${quebra} — pode haver mês faltando ou extrato substituído.`)
  }
  if (itens.length === 0) return null

  return (
    <div className="hairline flex items-start gap-3 rounded-xl bg-surface p-4">
      <TriangleAlert size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-ink">O que falta para os números ficarem completos</p>
        <ul className="mt-1 space-y-1 text-[12.5px] text-ink-2">
          {itens.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </div>
      <button
        onClick={onIrExtratos}
        className="hairline shrink-0 rounded-lg px-3 py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
      >
        Abrir Extratos
      </button>
    </div>
  )
}

function lista(meses: string[]): string {
  const nomes = meses.map(fmtMes)
  return nomes.length > 6 ? `${nomes.slice(0, 6).join(', ')} e mais ${nomes.length - 6}` : nomes.join(', ')
}
