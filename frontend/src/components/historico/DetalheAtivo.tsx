import { useEffect, useState } from 'react'
import { getHistoricoAtivo, type HistoricoAtivo, type JanelaTipo } from '../../lib/api'
import { fmtBRL, fmtBRLSinal, fmtMes, fmtPctSinal, fmtQtde } from '../../lib/format'
import BadgeComposicao from './BadgeComposicao'

const AVISOS: Record<string, string> = {
  evento_societario: 'desdobramento, grupamento ou bonificação: o preço de referência foi ajustado',
  trazido_de_outra_corretora: 'parte veio de outra corretora (conta como aporte)',
  levado_para_outra_corretora: 'parte foi para outra corretora (conta como resgate)',
  evento_sem_preco_comparavel: 'evento societário sem preço comparável: mês sem número',
}

const seHouver = (v: number | null) => (v ? fmtBRL(v) : '—')

/** Um papel mês a mês no período — o que está por trás da linha da tabela. */
export default function DetalheAtivo({ chave, janela }: { chave: string; janela: JanelaTipo }) {
  const [dados, setDados] = useState<HistoricoAtivo | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    let vivo = true
    setDados(null)
    setErro(null)
    getHistoricoAtivo(chave, janela)
      .then((d) => vivo && setDados(d))
      .catch((e: Error) => vivo && setErro(e.message))
    return () => {
      vivo = false
    }
  }, [chave, janela])

  if (erro) return <p className="px-4 py-3 text-[12.5px] text-critical">Não consegui abrir o papel: {erro}</p>
  if (!dados) return <div className="shimmer mx-4 my-3 h-20 rounded-lg" />

  const meses = [...dados.meses].reverse()
  return (
    <div className="px-4 py-3">
      <table className="w-full min-w-[760px] border-collapse text-[12px]">
        <thead>
          <tr className="text-[10px] tracking-wider text-ink-3 uppercase">
            <th className="pr-3 pb-1.5 text-left font-semibold">Mês</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Quantidade</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Preço</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Compras</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Vendas</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Renda</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Resultado</th>
            <th className="px-3 pb-1.5 text-right font-semibold">Rentab.</th>
            <th className="pl-3 pb-1.5 text-left font-semibold">Situação</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {meses.map((m) => (
            <tr key={m.mes} className="border-t border-line/70 align-top">
              <td className="py-1.5 pr-3 font-medium text-ink">{fmtMes(m.mes)}</td>
              <td className="px-3 py-1.5 text-right text-ink-2">
                {m.quantidade_ini === m.quantidade_fim || m.status === 'sem_base'
                  ? fmtQtde(m.quantidade_fim)
                  : `${fmtQtde(m.quantidade_ini)} → ${fmtQtde(m.quantidade_fim)}`}
              </td>
              <td className="px-3 py-1.5 text-right text-ink-2">
                {m.status === 'sem_base' || m.preco_ini == null
                  ? fmtBRL(m.preco_fim)
                  : `${fmtBRL(m.preco_ini)} → ${fmtBRL(m.preco_fim)}`}
              </td>
              <td className="px-3 py-1.5 text-right text-ink-2">{seHouver(m.compras)}</td>
              <td className="px-3 py-1.5 text-right text-ink-2">{seHouver(m.vendas)}</td>
              <td className="px-3 py-1.5 text-right text-ink-2">{seHouver(m.renda)}</td>
              <td className="px-3 py-1.5 text-right font-medium text-ink">{fmtBRLSinal(m.resultado)}</td>
              <td className="px-3 py-1.5 text-right text-ink-2">{fmtPctSinal(m.rentabilidade_pct)}</td>
              <td className="py-1.5 pl-3">
                <BadgeComposicao status={m.status} />
                {m.aviso && <p className="mt-0.5 max-w-[220px] text-[11px] text-ink-3">{AVISOS[m.aviso] ?? m.aviso}</p>}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="tabular-nums">
          <tr className="border-t border-baseline">
            <td className="py-1.5 pr-3 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">Período</td>
            <td colSpan={2} />
            <td className="px-3 py-1.5 text-right text-ink-2">{seHouver(dados.acumulado.compras)}</td>
            <td className="px-3 py-1.5 text-right text-ink-2">{seHouver(dados.acumulado.vendas)}</td>
            <td className="px-3 py-1.5 text-right text-ink-2">{seHouver(dados.acumulado.renda)}</td>
            <td className="px-3 py-1.5 text-right font-semibold text-ink">{fmtBRLSinal(dados.acumulado.resultado)}</td>
            <td className="px-3 py-1.5 text-right font-medium text-ink">{fmtPctSinal(dados.acumulado.rentabilidade_pct)}</td>
            <td className="py-1.5 pl-3">
              <BadgeComposicao status={dados.acumulado.status} />
            </td>
          </tr>
        </tfoot>
      </table>
      <p className="mt-2 text-[11px] text-ink-3">
        Resultado = valor no fim − valor no início − compras + vendas + renda. Rentabilidade pelo
        preço unitário com a renda por cota, encadeada nos meses com número — aportes e resgates
        não a distorcem.
      </p>
    </div>
  )
}
