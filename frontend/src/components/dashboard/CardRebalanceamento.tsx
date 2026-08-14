import { ArrowDownRight, ArrowUpRight, CircleCheck, MessageSquare } from 'lucide-react'
import Card from './Card'
import type { Rebalanceamento, Sugestao } from '../../lib/api'
import { fmtBRL, fmtHora, fmtPP } from '../../lib/format'

interface Props {
  dados: Rebalanceamento | null
  carregando: boolean
  onPerguntar(): void
}

export default function CardRebalanceamento({
  dados,
  carregando,
  onPerguntar,
}: Props) {
  if (carregando) {
    return (
      <Card titulo="Rebalanceamento">
        <div className="shimmer h-16 rounded-lg" />
      </Card>
    )
  }

  if (!dados || dados.error) {
    return (
      <Card titulo="Rebalanceamento">
        <p className="text-[13px] text-ink-3">
          {dados?.error ?? 'Não consegui analisar agora.'}
        </p>
      </Card>
    )
  }

  const dentro = dados.status === 'dentro_da_banda'
  const sugestoes: Sugestao[] = [
    ...(dados.sugestoes_por_classe ?? []),
    ...(dados.sugestoes_por_ativo ?? []),
  ].sort((a, b) => b.valor_a_mover - a.valor_a_mover)

  return (
    <Card titulo="Rebalanceamento">
      <div className="mb-3 flex items-start gap-2.5">
        {dentro ? (
          <CircleCheck size={16} className="mt-0.5 shrink-0 text-good" />
        ) : (
          <ArrowUpRight size={16} className="mt-0.5 shrink-0 text-warn" />
        )}
        <div className="min-w-0">
          <p className="text-[14px] font-medium">
            {dentro
              ? 'Dentro da banda — nenhum ajuste necessário'
              : `${dados.total_sugestoes ?? sugestoes.length} ajuste(s) sugerido(s)`}
          </p>
          <p className="text-[11.5px] text-ink-3">
            Análise às {fmtHora(dados.data_analise)}
            {dados.snapshot?.as_of_mais_antigo &&
              ` · dado mais antigo de ${fmtHora(dados.snapshot.as_of_mais_antigo)}`}
          </p>
        </div>
      </div>

      {sugestoes.length > 0 && (
        <ul className="space-y-2">
          {sugestoes.map((s, i) => {
            const reduzir = s.acao === 'REDUZIR'
            const Icone = reduzir ? ArrowDownRight : ArrowUpRight
            return (
              <li
                key={`${s.acao}-${s.ativo ?? s.classe ?? i}`}
                className="flex items-start gap-2.5 rounded-lg bg-surface-2 p-2.5"
              >
                <span
                  className={`mt-0.5 flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${
                    reduzir
                      ? 'bg-critical/15 text-critical'
                      : 'bg-s1/15 text-s1'
                  }`}
                >
                  <Icone size={11} />
                  {s.acao}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] leading-snug text-ink">
                    {s.razao}
                    {s.nivel === 'ativo' && s.ativo && (
                      <span className="font-medium"> · {s.ativo}</span>
                    )}
                  </p>
                  <p className="mt-0.5 text-[11.5px] text-ink-3 tabular-nums">
                    Mover aprox. {fmtBRL(s.valor_a_mover)} · desvio{' '}
                    {fmtPP(s.desvio_pp)}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {dados.nota_alvos_ativo && (
        <p className="mt-3 text-[11.5px] text-ink-3">{dados.nota_alvos_ativo}</p>
      )}

      <button
        onClick={onPerguntar}
        className="hairline mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2 text-[12.5px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
      >
        <MessageSquare size={13} />
        Pedir a análise ao consultor
      </button>
    </Card>
  )
}
