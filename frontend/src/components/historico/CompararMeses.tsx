import { useEffect, useMemo, useState } from 'react'
import { compararMeses, type Comparacao, type ExtratoResumo, type LinhaComparacao } from '../../lib/api'
import { corDaClasse, ordemDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtBRLSinal, fmtData, fmtMes, fmtPP, fmtPctBR, fmtPctSinal, fmtQtde } from '../../lib/format'
import BarraAlocacao from '../dashboard/BarraAlocacao'
import Card from '../dashboard/Card'

const rotuloMes = (m: ExtratoResumo) =>
  m.periodo_mensal ? fmtMes(m.data_referencia) : `até ${fmtData(m.data_referencia)}`

/**
 * Dois fechamentos lado a lado: o que entrou, saiu e mudou de quantidade, a
 * alocação nas duas datas e o que aconteceu entre elas (rentabilidade, aportes,
 * proventos). Por padrão, os dois meses mais recentes.
 */
export default function CompararMeses({ meses }: { meses: ExtratoResumo[] }) {
  const ordenados = useMemo(
    () => [...meses].sort((a, b) => a.data_referencia.localeCompare(b.data_referencia)),
    [meses],
  )
  const [de, setDe] = useState<string | null>(null)
  const [ate, setAte] = useState<string | null>(null)
  const [dados, setDados] = useState<Comparacao | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  // Escolha inicial e reparo quando um mês escolhido some da lista (exclusão).
  useEffect(() => {
    const datas = new Set(ordenados.map((m) => m.data_referencia))
    const n = ordenados.length
    if (n < 2) return
    if (!ate || !datas.has(ate)) setAte(ordenados[n - 1].data_referencia)
    if (!de || !datas.has(de)) setDe(ordenados[n - 2].data_referencia)
  }, [ordenados, de, ate])

  useEffect(() => {
    if (!de || !ate || de >= ate) {
      setDados(null)
      return
    }
    let vivo = true
    setErro(null)
    compararMeses(de, ate)
      .then((d) => vivo && setDados(d))
      .catch((e: Error) => vivo && setErro(e.message))
    return () => {
      vivo = false
    }
  }, [de, ate])

  if (ordenados.length < 2) return null

  const seletor = (valor: string | null, mudar: (v: string) => void, rotulo: string) => (
    <label className="flex items-center gap-1.5 text-[12px] text-ink-3">
      {rotulo}
      <select
        value={valor ?? ''}
        onChange={(e) => mudar(e.target.value)}
        className="hairline rounded-md bg-surface-2 px-2 py-1 text-[12.5px] text-ink"
      >
        {ordenados.map((m) => (
          <option key={m.data_referencia} value={m.data_referencia}>
            {rotuloMes(m)}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <Card
      titulo="Comparar dois meses"
      acao={
        <div className="flex flex-wrap items-center gap-2">
          {seletor(de, setDe, 'de')}
          {seletor(ate, setAte, 'até')}
        </div>
      }
    >
      {de && ate && de >= ate && (
        <p className="text-[13px] text-ink-3">Escolha um mês inicial anterior ao final.</p>
      )}
      {erro && <p className="text-[13px] text-critical">Não consegui comparar: {erro}</p>}
      {!erro && de && ate && de < ate && !dados && <div className="shimmer h-40 rounded-lg" />}
      {dados && <Resultado dados={dados} />}
    </Card>
  )
}

function Resultado({ dados }: { dados: Comparacao }) {
  const p = dados.periodo
  const classes = [...dados.classes].sort((a, b) => ordemDaClasse(a.classe) - ordemDaClasse(b.classe))
  const grupos: { id: keyof Comparacao['posicoes']; rotulo: string; aberto: boolean }[] = [
    { id: 'entraram', rotulo: 'Entraram', aberto: true },
    { id: 'sairam', rotulo: 'Saíram', aberto: true },
    { id: 'mudaram', rotulo: 'Mudaram de quantidade', aberto: true },
    { id: 'mantidos', rotulo: 'Mesma quantidade (só o preço mudou)', aberto: false },
  ]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Numero rotulo="Posições e caixa">
          {fmtBRL(dados.total_de)} → {fmtBRL(dados.total_ate)}
          <span className="ml-1.5 text-[12px] text-ink-3">{fmtBRLSinal(dados.total_ate - dados.total_de)}</span>
        </Numero>
        <Numero
          rotulo={`Rentabilidade entre as datas${p.provisorio ? ' (provisória)' : ''}`}
          dica={
            p.faltantes.length
              ? `Sem número em ${p.faltantes.map(fmtMes).join(', ')}: acumulado de ${p.considerados.length} de ${p.meses.length} meses.`
              : undefined
          }
        >
          {fmtPctSinal(p.rentabilidade_pct)}
          {p.faltantes.length > 0 && (
            <span className="ml-1.5 text-[12px] text-ink-3">
              {p.considerados.length} de {p.meses.length} meses
            </span>
          )}
        </Numero>
        <Numero rotulo="Aportes líquidos · proventos">
          {fmtBRLSinal(p.aportes_liquidos)}
          <span className="ml-1.5 text-[12px] text-ink-3">· {fmtBRL(p.proventos)}</span>
        </Numero>
      </div>

      <div>
        <p className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">Alocação</p>
        <div className="space-y-3">
          {[
            { rotulo: fmtData(dados.de), chave: 'valor_de' as const, total: dados.total_de },
            { rotulo: fmtData(dados.ate), chave: 'valor_ate' as const, total: dados.total_ate },
          ].map((lado) => (
            <div key={lado.chave} className="grid grid-cols-1 gap-1 sm:grid-cols-[88px_1fr] sm:items-start sm:gap-3">
              <span className="pt-2 text-[12px] text-ink-3 tabular-nums">{lado.rotulo}</span>
              <BarraAlocacao
                classes={classes.map((c) => ({ classe: c.classe, valor: c[lado.chave] }))}
                total={lado.total}
              />
            </div>
          ))}
        </div>
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
          {classes
            .filter((c) => c.peso_de != null && c.peso_ate != null && Math.abs(c.peso_ate - c.peso_de) >= 0.05)
            .map((c) => (
              <li key={c.classe} className="tabular-nums">
                {rotuloDaClasse(c.classe)}: {fmtPctBR(c.peso_de, 1)} → {fmtPctBR(c.peso_ate, 1)}{' '}
                <span className="text-ink-3">({fmtPP(c.peso_ate! - c.peso_de!)})</span>
              </li>
            ))}
        </ul>
      </div>

      <div className="space-y-2">
        {grupos.map((g) => {
          const linhas = dados.posicoes[g.id]
          if (linhas.length === 0) return null
          return (
            <details key={g.id} open={g.aberto}>
              <summary className="cursor-pointer text-[11px] font-semibold tracking-wider text-ink-3 uppercase select-none hover:text-ink-2">
                {g.rotulo} ({linhas.length})
              </summary>
              <TabelaLinhas linhas={linhas} />
            </details>
          )
        })}
      </div>
    </div>
  )
}

function Numero({ rotulo, dica, children }: { rotulo: string; dica?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-surface-2/60 p-3" title={dica}>
      <p className="text-[11px] text-ink-3">{rotulo}</p>
      <p className="mt-0.5 text-[14px] font-medium text-ink tabular-nums">{children}</p>
    </div>
  )
}

function TabelaLinhas({ linhas }: { linhas: LinhaComparacao[] }) {
  return (
    <div className="-mx-4 mt-1 overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[12.5px]">
        <thead>
          <tr className="text-[10.5px] tracking-wider text-ink-3 uppercase">
            <th className="px-4 py-1.5 text-left font-semibold">Ativo</th>
            <th className="px-4 py-1.5 text-right font-semibold">Quantidade</th>
            <th className="px-4 py-1.5 text-right font-semibold">Valor</th>
            <th className="px-4 py-1.5 text-right font-semibold">Variação</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {linhas.map((l) => (
            <tr key={l.chave} className="border-t border-line">
              <td className="px-4 py-1.5">
                <span className="inline-flex items-center gap-2 whitespace-nowrap">
                  <span
                    className="size-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: corDaClasse(l.classe) }}
                    aria-hidden="true"
                  />
                  <span className="font-medium text-ink">{l.ticker ?? l.nome ?? l.chave}</span>
                  <span className="text-[11px] text-ink-3">{rotuloDaClasse(l.classe)}</span>
                </span>
              </td>
              <td className="px-4 py-1.5 text-right text-ink-2">
                {l.quantidade_de === l.quantidade_ate
                  ? fmtQtde(l.quantidade_ate)
                  : `${l.quantidade_de == null ? '—' : fmtQtde(l.quantidade_de)} → ${l.quantidade_ate == null ? '—' : fmtQtde(l.quantidade_ate)}`}
              </td>
              <td className="px-4 py-1.5 text-right text-ink-2">
                {l.valor_de == null ? '—' : fmtBRL(l.valor_de)} → {l.valor_ate == null ? '—' : fmtBRL(l.valor_ate)}
              </td>
              <td className="px-4 py-1.5 text-right font-medium text-ink">{fmtBRLSinal(l.variacao)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
