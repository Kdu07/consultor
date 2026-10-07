import { Fragment, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, ChevronsUpDown, ArrowDown, ArrowUp } from 'lucide-react'
import type { AtivoComposicao, JanelaTipo } from '../../lib/api'
import { corDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtBRLSinal, fmtPctBR, fmtPctSinal } from '../../lib/format'
import BadgeComposicao from './BadgeComposicao'
import BarraResultado from './BarraResultado'
import DetalheAtivo from './DetalheAtivo'

type Coluna = 'ativo' | 'resultado' | 'rentabilidade_pct' | 'renda' | 'valor_fim' | 'peso_fim_pct'

const COLUNAS: { id: Coluna; rotulo: string; direita?: boolean }[] = [
  { id: 'ativo', rotulo: 'Ativo' },
  { id: 'resultado', rotulo: 'Resultado', direita: true },
  { id: 'rentabilidade_pct', rotulo: 'Rentab.', direita: true },
  { id: 'renda', rotulo: 'Renda', direita: true },
  { id: 'valor_fim', rotulo: 'No fim', direita: true },
  { id: 'peso_fim_pct', rotulo: 'Peso', direita: true },
]

const nome = (a: AtivoComposicao) => a.ticker ?? a.nome ?? a.chave

/**
 * Todos os papéis do período, ordenáveis por qualquer coluna (sem número vai
 * para o fim, nos dois sentidos). Clicar no papel abre o mês a mês dele.
 */
export default function TabelaAtivos({ ativos, janela }: { ativos: AtivoComposicao[]; janela: JanelaTipo }) {
  const [ordem, setOrdem] = useState<{ coluna: Coluna; desc: boolean }>({ coluna: 'resultado', desc: true })
  const [aberto, setAberto] = useState<string | null>(null)

  const ordenados = useMemo(() => {
    const coluna = ordem.coluna
    const valor = (a: AtivoComposicao): number | string | null =>
      coluna === 'ativo' ? nome(a) : a[coluna]
    return [...ativos].sort((a, b) => {
      const va = valor(a)
      const vb = valor(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const cmp = typeof va === 'string' ? va.localeCompare(String(vb), 'pt-BR') : va - (vb as number)
      return ordem.desc ? -cmp : cmp
    })
  }, [ativos, ordem])

  const maior = Math.max(0, ...ativos.map((a) => Math.abs(a.resultado ?? 0)))

  function ordenar(coluna: Coluna) {
    setOrdem((o) => (o.coluna === coluna ? { coluna, desc: !o.desc } : { coluna, desc: coluna !== 'ativo' }))
  }

  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
            {COLUNAS.slice(0, 1).map((c) => (
              <Cabecalho key={c.id} coluna={c} ordem={ordem} onOrdenar={ordenar} />
            ))}
            <th className="w-[18%] px-4 pb-2">
              <span className="sr-only">Resultado em barra</span>
            </th>
            {COLUNAS.slice(1).map((c) => (
              <Cabecalho key={c.id} coluna={c} ordem={ordem} onOrdenar={ordenar} />
            ))}
            <th className="px-4 pb-2 text-left font-semibold">Situação</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {ordenados.map((a) => {
            const expandido = aberto === a.chave
            return (
              <Fragment key={a.chave}>
                <tr className={`border-t border-line transition-colors ${expandido ? 'bg-surface-2' : 'hover:bg-surface-2/60'}`}>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => setAberto(expandido ? null : a.chave)}
                      aria-expanded={expandido}
                      className="flex items-center gap-2 text-left whitespace-nowrap"
                    >
                      {expandido ? (
                        <ChevronDown size={13} className="shrink-0 text-ink-3" aria-hidden="true" />
                      ) : (
                        <ChevronRight size={13} className="shrink-0 text-ink-3" aria-hidden="true" />
                      )}
                      <span
                        className="size-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: corDaClasse(a.classe) }}
                        aria-hidden="true"
                      />
                      <span className="font-medium text-ink hover:underline">{nome(a)}</span>
                      <span className="text-[11px] text-ink-3">{rotuloDaClasse(a.classe)}</span>
                    </button>
                  </td>
                  <td className="px-4 py-2">
                    <BarraResultado valor={a.resultado} maior={maior} cor={corDaClasse(a.classe)} />
                  </td>
                  <td className="px-4 py-2 text-right font-medium text-ink">{fmtBRLSinal(a.resultado)}</td>
                  <td className="px-4 py-2 text-right text-ink-2">{fmtPctSinal(a.rentabilidade_pct)}</td>
                  <td className="px-4 py-2 text-right text-ink-2">{a.renda ? fmtBRL(a.renda) : '—'}</td>
                  <td className="px-4 py-2 text-right text-ink-2">{a.valor_fim ? fmtBRL(a.valor_fim) : 'vendido'}</td>
                  <td className="px-4 py-2 text-right text-ink-2">{fmtPctBR(a.peso_fim_pct, 1)}</td>
                  <td className="px-4 py-2">
                    <BadgeComposicao status={a.status} />
                  </td>
                </tr>
                {expandido && (
                  <tr className="bg-surface-2/40">
                    <td colSpan={COLUNAS.length + 2}>
                      <DetalheAtivo chave={a.chave} janela={janela} />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Cabecalho({
  coluna,
  ordem,
  onOrdenar,
}: {
  coluna: (typeof COLUNAS)[number]
  ordem: { coluna: Coluna; desc: boolean }
  onOrdenar(c: Coluna): void
}) {
  const ativa = ordem.coluna === coluna.id
  const Icone = !ativa ? ChevronsUpDown : ordem.desc ? ArrowDown : ArrowUp
  return (
    <th
      className={`px-4 pb-2 font-semibold whitespace-nowrap ${coluna.direita ? 'text-right' : 'text-left'}`}
      aria-sort={ativa ? (ordem.desc ? 'descending' : 'ascending') : 'none'}
    >
      <button
        onClick={() => onOrdenar(coluna.id)}
        className={`inline-flex items-center gap-1 uppercase transition-colors hover:text-ink ${ativa ? 'text-ink-2' : ''}`}
      >
        {coluna.rotulo}
        <Icone size={11} aria-hidden="true" className={ativa ? '' : 'opacity-50'} />
      </button>
    </th>
  )
}
