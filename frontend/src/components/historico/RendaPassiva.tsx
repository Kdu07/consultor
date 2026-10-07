import type { Desempenho } from '../../lib/api'
import { corDaClasse, ordemDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtBRLCompacto, fmtMes, fmtMesLongo, fmtPctBR } from '../../lib/format'
import Card from '../dashboard/Card'
import GraficoColunas from './GraficoColunas'

interface Props {
  proventos: Desempenho['proventos']
  /** Meses do recorte escolhido acima (mesma janela dos outros gráficos). */
  meses: string[]
}

/**
 * Renda passiva: proventos por mês (uma série só) e a divisão por classe em
 * barras separadas, cada uma com seu rótulo. Empilhar por classe poria lado a
 * lado cores de classe que não passam na validação de daltonismo quando uma
 * classe intermediária falta (ex.: FIIs ao lado do Tesouro) — então a
 * composição vai para uma lista, não para a pilha.
 */
export default function RendaPassiva({ proventos, meses }: Props) {
  const porMes = new Map(proventos.por_mes.map((p) => [p.mes, p]))
  const valores = meses.map((m) => porMes.get(m)?.total ?? null)

  const somaClasse = new Map<string, number>()
  for (const m of meses) {
    for (const [classe, v] of Object.entries(porMes.get(m)?.por_classe ?? {})) {
      somaClasse.set(classe, (somaClasse.get(classe) ?? 0) + v)
    }
  }
  const totalRecorte = [...somaClasse.values()].reduce((a, b) => a + b, 0)
  const classes = [...somaClasse.entries()]
    .filter(([, v]) => v > 0)
    .sort((a, b) => ordemDaClasse(a[0]) - ordemDaClasse(b[0]))
  const maiorClasse = Math.max(0, ...classes.map(([, v]) => v))

  const doze = proventos.ultimos_12m

  return (
    <Card titulo="Renda passiva">
      {doze && (
        <div className="mb-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <div>
            <p className="text-[11px] text-ink-3">Últimos 12 meses</p>
            <p className="text-[22px] font-semibold">{fmtBRL(doze.total)}</p>
          </div>
          {doze.yield_pct != null && (
            <div>
              <p className="text-[11px] text-ink-3">Sobre o patrimônio em posições</p>
              <p className="text-[15px] font-medium">{fmtPctBR(doze.yield_pct, 2)}</p>
            </div>
          )}
          {doze.parcial && (
            <p className="text-[11px] text-ink-3">
              Só {doze.meses_com_dado} {doze.meses_com_dado === 1 ? 'mês arquivado' : 'meses arquivados'} na janela
            </p>
          )}
        </div>
      )}

      {meses.length > 0 && (
        <GraficoColunas
          titulo="Proventos por mês"
          rotulos={meses.map(fmtMes)}
          valores={valores}
          cor="var(--color-ink-2)"
          formatarValor={fmtBRL}
          formatarEixo={(v) => fmtBRLCompacto(v)}
          rotuloTooltip={(i) => fmtMesLongo(meses[i])}
          detalheTooltip={(i) => {
            const p = porMes.get(meses[i])
            if (!p) return null
            return (
              <div className="mt-1 space-y-0.5 text-[11px] text-ink-3">
                {p.aluguel > 0 && <div>aluguel de ações {fmtBRL(p.aluguel)}</div>}
                {p.amortizacao > 0 && <div>amortização (fora da renda) {fmtBRL(p.amortizacao)}</div>}
                <div>{p.quantidade} pagamento(s)</div>
              </div>
            )
          }}
        />
      )}

      {classes.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
            Por classe no período
          </p>
          <ul className="space-y-2">
            {classes.map(([classe, v]) => (
              <li key={classe} className="grid grid-cols-[96px_1fr_auto] items-center gap-3 text-[12.5px]">
                <span className="text-ink-2">{classe === 'OUTRO' ? 'Outros' : rotuloDaClasse(classe)}</span>
                <span className="h-2 rounded-full bg-surface-2">
                  <span
                    className="block h-2 rounded-full"
                    style={{
                      width: `${Math.max(2, (v / maiorClasse) * 100)}%`,
                      backgroundColor: classe === 'OUTRO' ? 'var(--color-ink-3)' : corDaClasse(classe),
                    }}
                  />
                </span>
                <span className="text-right tabular-nums text-ink-2">
                  {fmtBRL(v)}
                  <span className="ml-2 text-ink-3">{fmtPctBR(totalRecorte ? (v / totalRecorte) * 100 : 0, 0)}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {proventos.por_ativo_12m.length > 0 && (
        <div className="mt-5">
          <p className="mb-1 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
            Quem pagou nos últimos 12 meses
          </p>
          <div className="-mx-4 overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-[12.5px]">
              <thead>
                <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
                  <th className="px-4 py-2 text-left font-semibold">Ativo</th>
                  <th className="px-4 py-2 text-right font-semibold">Recebido</th>
                  <th className="px-4 py-2 text-right font-semibold">Pagamentos</th>
                  <th className="px-4 py-2 text-right font-semibold">Sobre o valor atual</th>
                  <th className="px-4 py-2 text-right font-semibold">Sobre o custo</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {proventos.por_ativo_12m.slice(0, 12).map((a) => (
                  <tr key={a.chave} className="border-t border-line">
                    <td className="px-4 py-2">
                      <span className="inline-flex items-center gap-2">
                        <span
                          className="size-1.5 rounded-full"
                          style={{ backgroundColor: corDaClasse(a.classe) }}
                          aria-hidden="true"
                        />
                        <span className="font-medium text-ink">{a.ticker}</span>
                        <span className="text-[11px] text-ink-3">{rotuloDaClasse(a.classe)}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right text-ink">{fmtBRL(a.total)}</td>
                    <td className="px-4 py-2 text-right text-ink-2">{a.pagamentos}</td>
                    <td className="px-4 py-2 text-right text-ink-2">{fmtPctBR(a.yield_pct, 2)}</td>
                    <td className="px-4 py-2 text-right text-ink-2">{fmtPctBR(a.yield_sobre_custo_pct, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  )
}
