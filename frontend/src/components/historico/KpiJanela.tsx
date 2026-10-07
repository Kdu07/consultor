import { CircleDashed, CircleHelp } from 'lucide-react'
import type { JanelaDesempenho } from '../../lib/api'
import { fmtBRL, fmtMes, fmtPctBR, fmtPctSinal } from '../../lib/format'

interface Props {
  rotulo: string
  janela: JanelaDesempenho | undefined
}

/**
 * Um cartão por janela (mês, ano, 12 meses, desde o início): o número é a
 * rentabilidade descontados aportes e resgates; embaixo, CDI e IPCA dos MESMOS
 * meses. Quando a janela não é completa, o cartão diz por quê — ícone + texto.
 */
export default function KpiJanela({ rotulo, janela }: Props) {
  const periodo =
    janela?.de && janela.ate
      ? janela.de === janela.ate
        ? fmtMes(janela.de)
        : `${fmtMes(janela.de)} – ${fmtMes(janela.ate)}`
      : '—'

  return (
    <section className="hairline flex flex-col rounded-xl bg-surface p-4">
      <h3 className="text-[11px] font-semibold tracking-wider text-ink-3 uppercase">{rotulo}</h3>
      <p className="text-[11px] text-ink-3">{periodo}</p>

      <p className="mt-2 text-[26px] leading-none font-semibold">
        {fmtPctSinal(janela?.rentabilidade_pct)}
      </p>

      <dl className="mt-3 space-y-0.5 text-[12px] text-ink-2">
        <div className="flex justify-between gap-2">
          <dt className="text-ink-3">CDI</dt>
          <dd className="tabular-nums">
            {janela?.cdi_pct != null ? (
              <>
                {fmtPctSinal(janela.cdi_pct)}
                {janela.pct_do_cdi != null && (
                  <span className="text-ink-3"> · {fmtPctBR(janela.pct_do_cdi, 0)} do CDI</span>
                )}
              </>
            ) : (
              '—'
            )}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-ink-3">Acima do IPCA</dt>
          <dd className="tabular-nums">
            {janela?.retorno_real_pct != null
              ? fmtPctSinal(janela.retorno_real_pct)
              : janela?.ipca_pendente.length
                ? 'IPCA a publicar'
                : '—'}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-ink-3">Ganho</dt>
          <dd className="tabular-nums">{fmtBRL(janela?.ganho)}</dd>
        </div>
        {janela?.anualizado_pct != null && (
          <div className="flex justify-between gap-2">
            <dt className="text-ink-3">Ao ano</dt>
            <dd className="tabular-nums">{fmtPctSinal(janela.anualizado_pct)}</dd>
          </div>
        )}
      </dl>

      {(janela?.parcial || janela?.provisorio) && (
        <div className="mt-3 space-y-1 border-t border-line pt-2 text-[11px] text-ink-2">
          {janela.parcial && (
            <p className="flex items-start gap-1.5">
              <CircleDashed size={12} className="mt-[1px] shrink-0 text-ink-3" aria-hidden="true" />
              {janela.considerados.length} de {janela.meses} meses com rentabilidade
            </p>
          )}
          {janela.provisorio && (
            <p className="flex items-start gap-1.5">
              <CircleHelp size={12} className="mt-[1px] shrink-0 text-warn" aria-hidden="true" />
              Provisório: há lançamentos a classificar
            </p>
          )}
        </div>
      )}
    </section>
  )
}
