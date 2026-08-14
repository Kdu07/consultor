import { useState } from 'react'
import { Check, Copy, Sparkles, TriangleAlert, Wrench } from 'lucide-react'
import Markdown from './Markdown'
import { frasearTools, rotuloTool } from '../lib/tools'
import type { Mensagem as Msg } from '../lib/conversas'

interface Props {
  msg: Msg
  /** Tools rodando neste instante (só na mensagem que está sendo gerada). */
  rodando?: string[] | null
  streaming?: boolean
}

export default function Mensagem({ msg, rodando, streaming }: Props) {
  if (msg.papel === 'user') {
    return (
      <div className="fade-up flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">
          {msg.texto}
        </div>
      </div>
    )
  }

  return (
    <div className="fade-up group flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Sparkles size={14} strokeWidth={2} />
      </div>

      <div className="min-w-0 flex-1">
        {msg.tools && msg.tools.length > 0 && <ChipTools nomes={msg.tools} />}

        {rodando && rodando.length > 0 && (
          <div className="mb-2 flex items-center gap-2 text-[13px] text-ink-3">
            <Wrench size={13} className="animate-pulse" />
            <span>{frasearTools(rodando)}…</span>
          </div>
        )}

        {msg.texto ? (
          <div className={streaming ? 'caret-wrap' : undefined}>
            <Markdown>{msg.texto}</Markdown>
          </div>
        ) : streaming && (!rodando || rodando.length === 0) ? (
          <Esqueleto />
        ) : null}

        {msg.erro && (
          <div className="mt-2 flex items-center gap-2 text-[13px] text-serious">
            <TriangleAlert size={14} />
            <span>Falha na comunicação com o servidor.</span>
          </div>
        )}

        {!streaming && msg.texto && <Rodape msg={msg} />}
      </div>
    </div>
  )
}

function ChipTools({ nomes }: { nomes: string[] }) {
  const unicos = [...new Set(nomes)]
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5">
      {unicos.map((n) => (
        <span
          key={n}
          className="hairline inline-flex items-center gap-1.5 rounded-full bg-surface px-2.5 py-1 text-[11px] text-ink-3"
        >
          <Wrench size={11} />
          {rotuloTool(n)}
        </span>
      ))}
    </div>
  )
}

function Esqueleto() {
  return (
    <div className="space-y-2 py-1" aria-label="Gerando resposta">
      <div className="shimmer h-3 w-[70%] rounded" />
      <div className="shimmer h-3 w-[90%] rounded" />
      <div className="shimmer h-3 w-[45%] rounded" />
    </div>
  )
}

function Rodape({ msg }: { msg: Msg }) {
  const [copiado, setCopiado] = useState(false)

  async function copiar() {
    try {
      await navigator.clipboard.writeText(msg.texto)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 1600)
    } catch {
      /* clipboard bloqueado — silencioso */
    }
  }

  const m = msg.meta
  return (
    <div className="mt-2 flex items-center gap-3 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
      <button
        onClick={copiar}
        className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[12px] text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink-2"
        title="Copiar resposta"
      >
        {copiado ? <Check size={13} /> : <Copy size={13} />}
        {copiado ? 'Copiado' : 'Copiar'}
      </button>

      {m && (
        <span className="text-[11px] text-ink-3 tabular-nums">
          {m.iteracoes} iter · {m.tokensEntrada.toLocaleString('pt-BR')} in /{' '}
          {m.tokensSaida.toLocaleString('pt-BR')} out
          {m.custoUsd > 0 && ` · ~US$ ${m.custoUsd.toFixed(4)}`}
        </span>
      )}

      {m?.anomalia && (
        <span className="flex items-center gap-1 text-[11px] text-warn">
          <TriangleAlert size={11} /> resposta possivelmente incompleta
        </span>
      )}
    </div>
  )
}
