import { useState } from 'react'
import type { Posicao } from '../../lib/api'
import { corDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtData, fmtPct, fmtQtde } from '../../lib/format'

type Coluna = 'valor' | 'ticker' | 'percentual'

export default function TabelaPosicoes({ posicoes }: { posicoes: Posicao[] }) {
  const [ordem, setOrdem] = useState<Coluna>('valor')

  const linhas = [...posicoes].sort((a, b) => {
    if (ordem === 'ticker') {
      return (a.ticker ?? a.nome).localeCompare(b.ticker ?? b.nome)
    }
    return b[ordem] - a[ordem]
  })

  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[13px]">
        <thead>
          <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
            <Th onClick={() => setOrdem('ticker')} ativo={ordem === 'ticker'}>
              Ativo
            </Th>
            <Th>Classe</Th>
            <Th direita>Qtde</Th>
            <Th direita>P. médio</Th>
            <Th
              direita
              onClick={() => setOrdem('valor')}
              ativo={ordem === 'valor'}
            >
              Valor
            </Th>
            <Th
              direita
              onClick={() => setOrdem('percentual')}
              ativo={ordem === 'percentual'}
            >
              %
            </Th>
            <Th>Fonte</Th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {linhas.map((p) => (
            <tr
              key={p.id}
              className="border-t border-line transition-colors hover:bg-surface-2/60"
            >
              <td className="px-4 py-2.5">
                <div className="font-medium text-ink">
                  {p.ticker ?? p.nome}
                </div>
                {p.ticker && (
                  <div className="max-w-[190px] truncate text-[11px] text-ink-3">
                    {p.nome}
                  </div>
                )}
              </td>
              <td className="px-4 py-2.5">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] whitespace-nowrap text-ink-2">
                  <span
                    className="size-1.5 rounded-full"
                    style={{ backgroundColor: corDaClasse(p.classe) }}
                  />
                  {rotuloDaClasse(p.classe)}
                </span>
              </td>
              <td className="px-4 py-2.5 text-right text-ink-2">
                {fmtQtde(p.quantidade)}
              </td>
              <td className="px-4 py-2.5 text-right text-ink-2">
                {p.preco_medio ? fmtBRL(p.preco_medio) : '—'}
              </td>
              <td className="px-4 py-2.5 text-right font-medium">
                {fmtBRL(p.valor)}
              </td>
              <td className="px-4 py-2.5 text-right text-ink-2">
                {fmtPct(p.percentual)}
              </td>
              <td className="px-4 py-2.5">
                <div
                  className={`text-[10.5px] font-semibold tracking-wide ${
                    p.is_live ? 'text-good' : 'text-ink-3'
                  }`}
                >
                  {p.is_live ? 'AO VIVO' : 'EXTRATO'}
                </div>
                <div className="text-[10.5px] text-ink-3">
                  {fmtData(p.as_of)}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Th({
  children,
  direita,
  onClick,
  ativo,
}: {
  children?: React.ReactNode
  direita?: boolean
  onClick?(): void
  ativo?: boolean
}) {
  return (
    <th
      onClick={onClick}
      className={`px-4 pb-2 font-semibold whitespace-nowrap ${
        direita ? 'text-right' : 'text-left'
      } ${onClick ? 'cursor-pointer hover:text-ink-2' : ''} ${
        ativo ? 'text-ink-2' : ''
      }`}
    >
      {children}
      {ativo && <span className="ml-1">↓</span>}
    </th>
  )
}
