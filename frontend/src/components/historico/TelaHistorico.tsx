import { PanelLeftOpen } from 'lucide-react'
import AbaDesempenho from './AbaDesempenho'
import AbaExtratos from './AbaExtratos'

export type AbaHistorico = 'desempenho' | 'extratos'

interface Props {
  aba: AbaHistorico
  onAba(aba: AbaHistorico): void
  sidebarAberta: boolean
  onAbrirSidebar(): void
  /** Muda quando algo externo (um import pelo chat) exige recarregar. */
  chaveRecarga: number
  onPerguntar(texto: string): void
  /** Abre o import do mês pelo chat — com o arquivo já escolhido, quando vem do lote. */
  onImportar(arquivo?: File): void
}

const ABAS: { id: AbaHistorico; rotulo: string }[] = [
  { id: 'desempenho', rotulo: 'Desempenho' },
  { id: 'extratos', rotulo: 'Extratos' },
]

/**
 * Tela própria do histórico (docs/PLANO_HISTORICO.md, decisão 3 do dono): ocupa
 * o lugar do chat, em largura total — o painel lateral de 520px não comporta
 * os gráficos e a tabela mês a mês.
 */
export default function TelaHistorico({
  aba,
  onAba,
  sidebarAberta,
  onAbrirSidebar,
  chaveRecarga,
  onPerguntar,
  onImportar,
}: Props) {
  return (
    <div className="flex min-w-0 flex-1 flex-col bg-plane">
      <header className="flex h-12 shrink-0 items-center gap-2 px-3">
        {!sidebarAberta && (
          <button
            onClick={onAbrirSidebar}
            title="Abrir menu"
            className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <PanelLeftOpen size={16} />
          </button>
        )}
        <h1 className="text-[14px] font-semibold text-ink">Histórico</h1>
        <nav role="tablist" aria-label="Seções do histórico" className="ml-3 flex gap-1">
          {ABAS.map((a) => (
            <button
              key={a.id}
              role="tab"
              aria-selected={aba === a.id}
              onClick={() => onAba(a.id)}
              className={`rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                aba === a.id ? 'bg-surface-2 text-ink' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {a.rotulo}
            </button>
          ))}
        </nav>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1120px] px-4 pt-2 pb-8">
          {aba === 'desempenho' ? (
            <AbaDesempenho
              chaveRecarga={chaveRecarga}
              onIrExtratos={() => onAba('extratos')}
              onPerguntar={onPerguntar}
            />
          ) : (
            <AbaExtratos chaveRecarga={chaveRecarga} onImportar={onImportar} />
          )}
        </div>
      </div>
    </div>
  )
}
