import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChartCandlestick, PanelLeftOpen, PanelRightClose } from 'lucide-react'
import Composer from './Composer'
import EstadoVazio from './EstadoVazio'
import MensagemItem from './Mensagem'
import type { Conversa } from '../lib/conversas'

interface Props {
  conversa: Conversa
  ocupado: boolean
  streamingId: string | null
  toolsRodando: string[] | null
  sidebarAberta: boolean
  carteiraAberta: boolean
  onAbrirSidebar(): void
  onAlternarCarteira(): void
  onEnviar(texto: string): void
  onParar(): void
  onImportar(): void
}

export default function ChatView({
  conversa,
  ocupado,
  streamingId,
  toolsRodando,
  sidebarAberta,
  carteiraAberta,
  onAbrirSidebar,
  onAlternarCarteira,
  onEnviar,
  onParar,
  onImportar,
}: Props) {
  const [rascunho, setRascunho] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const grudadoRef = useRef(true)

  // Só acompanha o fim se o usuário já estava por lá — quem rolou para cima
  // para reler algo não é arrastado de volta a cada token.
  function aoRolar() {
    const el = scrollRef.current
    if (!el) return
    grudadoRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && grudadoRef.current) el.scrollTop = el.scrollHeight
  }, [conversa.mensagens, toolsRodando])

  useEffect(() => {
    grudadoRef.current = true
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [conversa.id])

  function enviar() {
    const texto = rascunho.trim()
    if (!texto || ocupado) return
    setRascunho('')
    onEnviar(texto)
  }

  const vazia = conversa.mensagens.length === 0

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

        <h1 className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink-2">
          {vazia ? '' : conversa.titulo}
        </h1>

        <button
          onClick={onAlternarCarteira}
          title={carteiraAberta ? 'Fechar carteira' : 'Abrir carteira'}
          className={`hairline flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors ${
            carteiraAberta
              ? 'bg-surface-2 text-ink'
              : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
          }`}
        >
          {carteiraAberta ? (
            <PanelRightClose size={14} />
          ) : (
            <ChartCandlestick size={14} />
          )}
          Carteira
        </button>
      </header>

      <div
        ref={scrollRef}
        onScroll={aoRolar}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {vazia ? (
          <EstadoVazio onPrompt={onEnviar} onImportar={onImportar} />
        ) : (
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-6 px-4 py-6">
            {conversa.mensagens.map((m) => (
              <MensagemItem
                key={m.id}
                msg={m}
                streaming={m.id === streamingId}
                rodando={m.id === streamingId ? toolsRodando : null}
              />
            ))}
          </div>
        )}
      </div>

      <Composer
        valor={rascunho}
        onChange={setRascunho}
        onEnviar={enviar}
        onParar={onParar}
        onAnexar={onImportar}
        ocupado={ocupado}
      />
    </div>
  )
}
