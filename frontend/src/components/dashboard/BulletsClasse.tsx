import { CircleCheck, TriangleAlert } from 'lucide-react'
import type { ClasseAlocacao } from '../../lib/api'
import { corDaClasse, ordemDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtPP, fmtPct } from '../../lib/format'

/**
 * Δ até o alvo, uma linha por classe: barra da alocação atual + marcador
 * vertical no alvo. Escala compartilhada entre as linhas, senão as barras não
 * são comparáveis entre si.
 */
export default function BulletsClasse({
  classes,
}: {
  classes: ClasseAlocacao[]
}) {
  const linhas = classes
    .filter((c) => c.valor > 0 || c.percentual_alvo > 0)
    .sort((a, b) => ordemDaClasse(a.classe) - ordemDaClasse(b.classe))

  if (linhas.length === 0) {
    return <p className="text-[13px] text-ink-3">Sem alvos definidos.</p>
  }

  const escala =
    Math.max(
      ...linhas.map((c) => Math.max(c.percentual_atual, c.percentual_alvo)),
    ) * 1.1 || 100

  return (
    <ul className="space-y-3.5">
      {linhas.map((c) => {
        const fora = c.fora_da_banda === true
        return (
          <li key={c.classe}>
            <div className="mb-1.5 flex items-baseline gap-2">
              <span
                className="size-2 shrink-0 translate-y-[-1px] rounded-[2px]"
                style={{ backgroundColor: corDaClasse(c.classe) }}
              />
              <span className="text-[13px] font-medium">
                {rotuloDaClasse(c.classe)}
              </span>
              <span className="ml-auto text-[12px] text-ink-3 tabular-nums">
                {fmtBRL(c.valor)}
              </span>
            </div>

            <div className="relative h-2.5 rounded-full bg-surface-2">
              <div
                className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-500"
                style={{
                  width: `${Math.min((c.percentual_atual / escala) * 100, 100)}%`,
                  backgroundColor: corDaClasse(c.classe),
                }}
              />
              {c.percentual_alvo > 0 && (
                <span
                  title={`Alvo: ${fmtPct(c.percentual_alvo)}`}
                  className="absolute -top-1 -bottom-1 w-0.5 rounded-full bg-ink-2"
                  style={{
                    left: `${Math.min((c.percentual_alvo / escala) * 100, 100)}%`,
                  }}
                />
              )}
            </div>

            <div className="mt-1.5 flex items-center gap-2 text-[12px] text-ink-3">
              <span className="tabular-nums">
                {fmtPct(c.percentual_atual)}
                {c.percentual_alvo > 0 && (
                  <> · alvo {fmtPct(c.percentual_alvo)}</>
                )}
              </span>

              {c.desvio_pp !== null && (
                <span
                  className={`ml-auto inline-flex items-center gap-1 tabular-nums ${
                    fora ? 'text-warn' : 'text-ink-3'
                  }`}
                >
                  {fora ? (
                    <TriangleAlert size={11} />
                  ) : (
                    <CircleCheck size={11} className="text-good" />
                  )}
                  {fmtPP(c.desvio_pp)}
                  <span className="text-ink-3">
                    {fora ? 'fora da banda' : 'na banda'}
                  </span>
                </span>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
