import { useState } from 'react'
import { corDaClasse, ordemDaClasse, rotuloDaClasse } from '../../lib/classes'
import { fmtBRL, fmtPct } from '../../lib/format'

/**
 * Parte-para-todo → barra empilhada horizontal (não rosca).
 * Os segmentos saem na ordem fixa das classes, nunca por valor: é essa ordem
 * que a validação de contraste CVD da paleta pressupõe.
 */
export default function BarraAlocacao({
  classes,
  total,
}: {
  classes: { classe: string; valor: number }[]
  total: number
}) {
  const [ativo, setAtivo] = useState<string | null>(null)

  const visiveis = classes
    .filter((c) => c.valor > 0)
    .sort((a, b) => ordemDaClasse(a.classe) - ordemDaClasse(b.classe))

  if (visiveis.length === 0 || total <= 0) {
    return <p className="text-[13px] text-ink-3">Sem posições para alocar.</p>
  }

  return (
    <div>
      <div className="flex h-9 gap-[2px] overflow-hidden rounded-md">
        {visiveis.map((c, i) => {
          const pct = (c.valor / total) * 100
          const primeiro = i === 0
          const ultimo = i === visiveis.length - 1
          return (
            <div
              key={c.classe}
              onMouseEnter={() => setAtivo(c.classe)}
              onMouseLeave={() => setAtivo(null)}
              style={{
                width: `${pct}%`,
                backgroundColor: corDaClasse(c.classe),
                borderTopLeftRadius: primeiro ? 4 : 0,
                borderBottomLeftRadius: primeiro ? 4 : 0,
                borderTopRightRadius: ultimo ? 4 : 0,
                borderBottomRightRadius: ultimo ? 4 : 0,
                opacity: ativo && ativo !== c.classe ? 0.45 : 1,
              }}
              className="flex min-w-[3px] items-center justify-center transition-opacity"
              title={`${rotuloDaClasse(c.classe)}: ${fmtPct(pct)} · ${fmtBRL(c.valor)}`}
            >
              {/* rótulo direto só onde cabe sem colidir */}
              {pct >= 11 && (
                <span className="px-1 text-[11px] font-semibold text-black/75 tabular-nums">
                  {pct.toFixed(0)}%
                </span>
              )}
            </div>
          )
        })}
      </div>

      {/* legenda sempre presente: identidade nunca depende só da cor */}
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {visiveis.map((c) => (
          <li
            key={c.classe}
            onMouseEnter={() => setAtivo(c.classe)}
            onMouseLeave={() => setAtivo(null)}
            className="flex items-center gap-1.5 text-[12px] text-ink-2"
          >
            <span
              className="size-2 shrink-0 rounded-[2px]"
              style={{ backgroundColor: corDaClasse(c.classe) }}
            />
            {rotuloDaClasse(c.classe)}
            <span className="text-ink-3 tabular-nums">
              {fmtPct((c.valor / total) * 100)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
