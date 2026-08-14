import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import Login from './components/Login'
import ModalImport from './components/ModalImport'
import PainelCarteira from './components/dashboard/PainelCarteira'
import { ProvedorToasts } from './components/Toasts'
import {
  definirHandlerNaoAutenticado,
  getAuthStatus,
  limparSessao,
  streamChat,
} from './lib/api'
import {
  carregarConversas,
  novaConversa,
  novoId,
  salvarConversas,
  tituloDe,
  type Conversa,
  type Mensagem,
} from './lib/conversas'

export default function App() {
  return (
    <ProvedorToasts>
      <Portao />
    </ProvedorToasts>
  )
}

/**
 * Decide entre a tela de senha e a aplicação. Em uso local (sem APP_PASSWORD)
 * o /auth/status já responde autenticado e isto some do caminho.
 */
function Portao() {
  const [estado, setEstado] = useState<'verificando' | 'dentro' | 'fora'>(
    'verificando',
  )

  const verificar = useCallback(() => {
    getAuthStatus()
      .then((s) => setEstado(s.authenticated ? 'dentro' : 'fora'))
      // Servidor sem o endpoint (versão antiga) ou fora do ar: não adianta
      // pedir senha — deixa a aplicação abrir e falhar com a mensagem dela.
      .catch(() => setEstado('dentro'))
  }, [])

  useEffect(() => {
    definirHandlerNaoAutenticado(() => setEstado('fora'))
    verificar()
  }, [verificar])

  if (estado === 'verificando') return <div className="h-dvh bg-plane" />
  if (estado === 'fora') return <Login onEntrou={() => setEstado('dentro')} />
  return <Aplicacao />
}

function Aplicacao() {
  const inicial = useMemo(() => {
    const salvas = carregarConversas()
    return salvas.length > 0 ? salvas : [novaConversa()]
  }, [])

  const [conversas, setConversas] = useState<Conversa[]>(inicial)
  const [ativaId, setAtivaId] = useState(inicial[0].id)

  const [streamingId, setStreamingId] = useState<string | null>(null)
  const [toolsRodando, setToolsRodando] = useState<string[] | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const [sidebarAberta, setSidebarAberta] = useState(
    () => window.innerWidth >= 1024,
  )
  const [carteiraAberta, setCarteiraAberta] = useState(false)
  const [importAberto, setImportAberto] = useState(false)
  const [chaveRecarga, setChaveRecarga] = useState(0)

  const ativa =
    conversas.find((c) => c.id === ativaId) ?? conversas[0] ?? novaConversa()

  // Persistência com folga: durante o streaming o texto muda a cada token.
  useEffect(() => {
    const t = setTimeout(() => salvarConversas(conversas), 400)
    return () => clearTimeout(t)
  }, [conversas])

  const patch = useCallback(
    (convId: string, msgId: string, fn: (m: Mensagem) => Mensagem) => {
      setConversas((cs) =>
        cs.map((c) =>
          c.id !== convId
            ? c
            : {
                ...c,
                mensagens: c.mensagens.map((m) => (m.id === msgId ? fn(m) : m)),
              },
        ),
      )
    },
    [],
  )

  const ocupado = streamingId !== null

  const enviar = useCallback(
    async (texto: string) => {
      if (ocupado || !texto.trim()) return

      const convId = ativaId
      const idUsuario = novoId('m')
      const idResposta = novoId('m')

      setConversas((cs) =>
        cs.map((c) =>
          c.id !== convId
            ? c
            : {
                ...c,
                titulo: c.mensagens.length === 0 ? tituloDe(texto) : c.titulo,
                mensagens: [
                  ...c.mensagens,
                  { id: idUsuario, papel: 'user', texto },
                  { id: idResposta, papel: 'assistant', texto: '' },
                ],
              },
        ),
      )

      setStreamingId(idResposta)
      setToolsRodando(null)

      const ctrl = new AbortController()
      abortRef.current = ctrl

      await streamChat(
        texto,
        convId,
        {
          onText: (d) =>
            patch(convId, idResposta, (m) => ({ ...m, texto: m.texto + d })),

          onTools: (nomes) => {
            setToolsRodando(nomes)
            patch(convId, idResposta, (m) => ({
              ...m,
              // separa o "deixa eu ver..." do bloco que vem depois das tools
              texto:
                m.texto && !m.texto.endsWith('\n') ? `${m.texto}\n\n` : m.texto,
              tools: [...(m.tools ?? []), ...nomes],
            }))
          },

          onToolsDone: () => setToolsRodando(null),

          onDone: (ev) => {
            patch(convId, idResposta, (m) => ({
              ...m,
              texto: ev.reply || m.texto,
              meta: {
                iteracoes: ev.iterations,
                tokensEntrada: ev.tokens_input,
                tokensSaida: ev.tokens_output,
                custoUsd: ev.cost_usd,
                anomalia: ev.anomaly,
              },
            }))
            // O turno pode ter gravado posições; só vale recarregar o que está à vista.
            if (carteiraAberta) setChaveRecarga((k) => k + 1)
          },

          onError: (msg) =>
            patch(convId, idResposta, (m) => ({
              ...m,
              texto: m.texto || msg,
              erro: true,
            })),
        },
        ctrl.signal,
      )

      abortRef.current = null
      setStreamingId(null)
      setToolsRodando(null)
    },
    [ativaId, carteiraAberta, ocupado, patch],
  )

  function parar() {
    abortRef.current?.abort()
    abortRef.current = null
    setStreamingId(null)
    setToolsRodando(null)
  }

  function criarConversa() {
    if (ocupado) parar()
    const nova = novaConversa()
    setConversas((cs) => [nova, ...cs])
    setAtivaId(nova.id)
    if (window.innerWidth < 1024) setSidebarAberta(false)
  }

  function excluir(id: string) {
    void limparSessao(id)
    setConversas((cs) => {
      const restantes = cs.filter((c) => c.id !== id)
      if (restantes.length === 0) {
        const nova = novaConversa()
        setAtivaId(nova.id)
        return [nova]
      }
      if (id === ativaId) setAtivaId(restantes[0].id)
      return restantes
    })
  }

  function selecionar(id: string) {
    setAtivaId(id)
    if (window.innerWidth < 1024) setSidebarAberta(false)
  }

  function abrirCarteira() {
    setCarteiraAberta(true)
    setChaveRecarga((k) => k + 1)
    if (window.innerWidth < 1024) setSidebarAberta(false)
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      {sidebarAberta && (
        <>
          <div
            className="fixed inset-0 z-30 bg-black/60 lg:hidden"
            onClick={() => setSidebarAberta(false)}
          />
          <div className="fixed inset-y-0 left-0 z-40 lg:static lg:z-auto">
            <Sidebar
              conversas={conversas}
              ativaId={ativa.id}
              onSelecionar={selecionar}
              onNova={criarConversa}
              onExcluir={excluir}
              onFechar={() => setSidebarAberta(false)}
              onImportar={() => setImportAberto(true)}
              onAbrirCarteira={abrirCarteira}
            />
          </div>
        </>
      )}

      <ChatView
        conversa={ativa}
        ocupado={ocupado}
        streamingId={streamingId}
        toolsRodando={toolsRodando}
        sidebarAberta={sidebarAberta}
        carteiraAberta={carteiraAberta}
        onAbrirSidebar={() => setSidebarAberta(true)}
        onAlternarCarteira={() =>
          carteiraAberta ? setCarteiraAberta(false) : abrirCarteira()
        }
        onEnviar={(t) => void enviar(t)}
        onParar={parar}
        onImportar={() => setImportAberto(true)}
      />

      {carteiraAberta && (
        <>
          <div
            className="fixed inset-0 z-30 bg-black/60 xl:hidden"
            onClick={() => setCarteiraAberta(false)}
          />
          {/* gaveta em telas estreitas; coluna fixa ao lado do chat a partir de xl
              (a largura em xl é do próprio painel — o wrapper precisa soltá-la) */}
          <div className="fixed inset-y-0 right-0 z-40 w-full max-w-[560px] xl:static xl:z-auto xl:w-auto xl:max-w-none xl:shrink-0">
            <PainelCarteira
              onFechar={() => setCarteiraAberta(false)}
              onPerguntar={(t) => {
                if (window.innerWidth < 1280) setCarteiraAberta(false)
                void enviar(t)
              }}
              chaveRecarga={chaveRecarga}
            />
          </div>
        </>
      )}

      <ModalImport
        aberto={importAberto}
        onFechar={() => setImportAberto(false)}
        onImportado={() =>
          void enviar('Importe o extrato que acabei de enviar.')
        }
      />
    </div>
  )
}
