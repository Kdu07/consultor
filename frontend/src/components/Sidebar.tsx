import {
  ChartCandlestick,
  FileText,
  HeartPulse,
  MessageSquarePlus,
  PanelLeftClose,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { agruparPorPeriodo, type Conversa } from '../lib/conversas'

interface Props {
  conversas: Conversa[]
  ativaId: string
  onSelecionar(id: string): void
  onNova(): void
  onExcluir(id: string): void
  onFechar(): void
  onImportar(): void
  onAbrirCarteira(): void
}

export default function Sidebar({
  conversas,
  ativaId,
  onSelecionar,
  onNova,
  onExcluir,
  onFechar,
  onImportar,
  onAbrirCarteira,
}: Props) {
  const grupos = agruparPorPeriodo(conversas)

  return (
    <aside className="hairline-r flex h-full w-[264px] shrink-0 flex-col bg-surface">
      <div className="flex items-center gap-2 px-3 py-3">
        <div className="flex size-7 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Sparkles size={15} />
        </div>
        <span className="flex-1 truncate text-[14px] font-semibold">
          Consultor
        </span>
        <button
          onClick={onFechar}
          title="Recolher menu"
          className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      <div className="px-3 pb-2">
        <button
          onClick={onNova}
          className="hairline flex w-full items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-surface-2"
        >
          <MessageSquarePlus size={15} />
          Nova conversa
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {grupos.length === 0 && (
          <p className="px-2 py-6 text-center text-[12px] text-ink-3">
            Suas conversas aparecem aqui.
          </p>
        )}

        {grupos.map((g) => (
          <div key={g.rotulo} className="mb-3">
            <h2 className="px-2 pb-1 text-[11px] font-medium tracking-wide text-ink-3 uppercase">
              {g.rotulo}
            </h2>
            <ul>
              {g.itens.map((c) => {
                const ativa = c.id === ativaId
                return (
                  <li key={c.id} className="group relative">
                    <button
                      onClick={() => onSelecionar(c.id)}
                      className={`w-full truncate rounded-lg py-2 pr-8 pl-2.5 text-left text-[13px] transition-colors ${
                        ativa
                          ? 'bg-surface-2 text-ink'
                          : 'text-ink-2 hover:bg-surface-2/60 hover:text-ink'
                      }`}
                    >
                      {c.titulo}
                    </button>
                    <button
                      onClick={() => onExcluir(c.id)}
                      title="Excluir conversa"
                      className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-md p-1.5 text-ink-3 opacity-0 transition-all group-hover:opacity-100 hover:bg-surface-3 hover:text-critical focus-visible:opacity-100"
                    >
                      <Trash2 size={13} />
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="hairline-t p-2">
        <ItemRodape
          icone={<ChartCandlestick size={15} />}
          rotulo="Carteira"
          onClick={onAbrirCarteira}
        />
        <ItemRodape
          icone={<FileText size={15} />}
          rotulo="Importar extrato"
          onClick={onImportar}
        />
        <div className="mt-1 flex items-center gap-3 px-2.5 py-1.5 text-[11px] text-ink-3">
          <a
            href="/health"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 transition-colors hover:text-ink-2"
          >
            <HeartPulse size={11} /> health
          </a>
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="transition-colors hover:text-ink-2"
          >
            /docs
          </a>
        </div>
      </div>
    </aside>
  )
}

function ItemRodape({
  icone,
  rotulo,
  onClick,
}: {
  icone: React.ReactNode
  rotulo: string
  onClick(): void
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
    >
      <span className="text-ink-3">{icone}</span>
      {rotulo}
    </button>
  )
}
