import type { ClasseComposicao, Composicao } from '../../lib/api'
import { corDaClasse, ordemDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtBRLSinal, fmtPctBR, fmtPctSinal } from '../../lib/format'
import BadgeComposicao from './BadgeComposicao'
import BarraResultado from './BarraResultado'

interface Props {
  classes: ClasseComposicao[]
  caixa: Composicao['caixa']
}

/**
 * Resultado por classe no período, na ordem fixa das classes. O caixa fecha a
 * tabela: rendimento do saldo e os custos que não são de nenhum papel.
 */
export default function TabelaClasses({ classes, caixa }: Props) {
  const linhas = [...classes].sort((a, b) => ordemDaClasse(a.classe) - ordemDaClasse(b.classe))
  const maior = Math.max(0, ...linhas.map((c) => Math.abs(c.resultado ?? 0)))

  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[700px] border-collapse text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
            <Th>Classe</Th>
            <Th largura="w-[22%]">
              <span className="sr-only">Resultado em barra</span>
            </Th>
            <Th direita>Resultado</Th>
            <Th direita>Rentab.</Th>
            <Th direita>Renda</Th>
            <Th direita>No fim</Th>
            <Th direita>Peso</Th>
            <Th>Situação</Th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {linhas.map((c) => (
            <tr key={c.classe} className="border-t border-line">
              <td className="px-4 py-2">
                <span className="inline-flex items-center gap-2">
                  <span
                    className="size-2 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: corDaClasse(c.classe) }}
                    aria-hidden="true"
                  />
                  <span className="font-medium whitespace-nowrap text-ink">{rotuloDaClasse(c.classe)}</span>
                </span>
              </td>
              <td className="px-4 py-2">
                <BarraResultado valor={c.resultado} maior={maior} cor={corDaClasse(c.classe)} />
              </td>
              <td className="px-4 py-2 text-right font-medium text-ink">{fmtBRLSinal(c.resultado)}</td>
              <td
                className="px-4 py-2 text-right text-ink-2"
                title={
                  c.rentabilidade_pct == null
                    ? 'Sem percentual: a classe entrou ou saiu da carteira no período, ou faltou o mês anterior.'
                    : `Modified Dietz da classe, encadeado em ${c.meses_com_numero} de ${c.meses} mês(es).`
                }
              >
                {fmtPctSinal(c.rentabilidade_pct)}
              </td>
              <td className="px-4 py-2 text-right text-ink-2">{fmtBRL(c.renda)}</td>
              <td className="px-4 py-2 text-right text-ink-2">{fmtBRL(c.valor_fim)}</td>
              <td className="px-4 py-2 text-right text-ink-2">{fmtPctBR(c.peso_fim_pct, 1)}</td>
              <td className="px-4 py-2">
                <BadgeComposicao status={c.status} />
              </td>
            </tr>
          ))}
          {caixa && (
            <tr className="border-t border-line">
              <td className="px-4 py-2">
                <span className="inline-flex items-center gap-2">
                  <span
                    className="size-2 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: corDaClasse('CAIXA') }}
                    aria-hidden="true"
                  />
                  <span className="font-medium whitespace-nowrap text-ink">Caixa e custos</span>
                </span>
              </td>
              <td className="px-4 py-2" />
              <td
                className="px-4 py-2 text-right font-medium text-ink"
                title={`Rendimento do saldo ${fmtBRL(caixa.rendimento)} · impostos e taxas avulsos ${fmtBRL(caixa.custos)}`}
              >
                {fmtBRLSinal(caixa.rendimento + caixa.custos)}
              </td>
              <td className="px-4 py-2 text-right text-ink-3">—</td>
              <td className="px-4 py-2 text-right text-ink-2">{fmtBRL(caixa.rendimento)}</td>
              <td className="px-4 py-2 text-right text-ink-2">{fmtBRL(caixa.valor_fim)}</td>
              <td className="px-4 py-2 text-right text-ink-2">{fmtPctBR(caixa.peso_fim_pct, 1)}</td>
              <td className="px-4 py-2" />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function Th({
  children,
  direita,
  largura,
}: {
  children?: React.ReactNode
  direita?: boolean
  largura?: string
}) {
  return (
    <th
      className={`px-4 pb-2 font-semibold whitespace-nowrap ${direita ? 'text-right' : 'text-left'} ${largura ?? ''}`}
    >
      {children}
    </th>
  )
}
