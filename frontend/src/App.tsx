import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import Login from './components/Login'
import ModalImport from './components/ModalImport'
import PainelCarteira from './components/dashboard/PainelCarteira'
import TelaHistorico, { type AbaHistorico } from './components/historico/TelaHistorico'
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

type Tela = 'chat' | 'historico'

/**
 * A tela vive no hash (#historico, #historico/extratos): sem router — o FastAPI
 * só serve "/" —, mas o botão voltar do navegador funciona e dá para guardar o link.
 */
function lerHash(): { tela: Tela; aba: AbaHistorico } {
  const h = window.location.hash
  if (h.startsWith('#historico')) {
    return { tela: 'historico', aba: h === '#historico/extratos' ? 'extratos' : 'desempenho' }
  }
  return { tela: 'chat', aba: 'desempenho' }
}

function Aplicacao() {
  const inicial = useMemo(() => {
    const salvas = carregarConversas()
    return salvas.length > 0 ? salvas : [novaConversa()]
  }, [])

  const [conversas, setConversas] = useState<Conversa[]>(inicial)
  const [ativaId, setAtivaId] = useState(inicial[0].id)
  // O rascunho mora aqui, não no ChatView: trocar para o Histórico desmonta o chat.
  const [rascunho, setRascunho] = useState('')

  const [streamingId, setStreamingId] = useState<string | null>(null)
  const [toolsRodando, setToolsRodando] = useState<string[] | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const [sidebarAberta, setSidebarAberta] = useState(
    () => window.innerWidth >= 1024,
  )
  const [carteiraAberta, setCarteiraAberta] = useState(false)
  const [importAberto, setImportAberto] = useState(false)
  const [arquivoImport, setArquivoImport] = useState<File | null>(null)
  const [chaveRecarga, setChaveRecarga] = useState(0)
  const [{ tela, aba }, setNavegacao] = useState(lerHash)

  // O fim do turno decide o que recarregar pelo que está à vista AGORA, não no
  // começo do turno: daí refs, e não o valor capturado pelo callback.
  const telaRef = useRef(tela)
  telaRef.current = tela
  const carteiraRef = useRef(carteiraAberta)
  carteiraRef.current = carteiraAberta

  useEffect(() => {
    const ouvir = () => setNavegacao(lerHash())
    window.addEventListener('hashchange', ouvir)
    window.addEventListener('popstate', ouvir)
    return () => {
      window.removeEventListener('hashchange', ouvir)
      window.removeEventListener('popstate', ouvir)
    }
  }, [])

  const irPara = useCallback((t: Tela, a: AbaHistorico = 'desempenho') => {
    const hash = t === 'chat' ? '' : a === 'extratos' ? '#historico/extratos' : '#historico'
    if (window.location.hash !== hash) {
      if (hash) window.history.pushState(null, '', hash)
      else window.history.pushState(null, '', window.location.pathname + window.location.search)
    }
    setNavegacao({ tela: t, aba: a })
  }, [])

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
            if (carteiraRef.current || telaRef.current === 'historico') {
              setChaveRecarga((k) => k + 1)
            }
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
    [ativaId, ocupado, patch],
  )

  // Mensagem que chegou com o chat ocupado (ex.: um upload que terminou no meio
  // de uma resposta) espera a vez em vez de sumir.
  const filaRef = useRef<string | null>(null)
  const enviarOuEnfileirar = useCallback(
    (texto: string) => {
      if (ocupado) filaRef.current = texto
      else void enviar(texto)
    },
    [enviar, ocupado],
  )
  useEffect(() => {
    if (!ocupado && filaRef.current) {
      const texto = filaRef.current
      filaRef.current = null
      void enviar(texto)
    }
  }, [enviar, ocupado])

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
    irPara('chat')
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
    irPara('chat')
    if (window.innerWidth < 1024) setSidebarAberta(false)
  }

  function abrirCarteira() {
    irPara('chat')
    setCarteiraAberta(true)
    setChaveRecarga((k) => k + 1)
    if (window.innerWidth < 1024) setSidebarAberta(false)
  }

  function abrirHistorico(a: AbaHistorico = 'desempenho') {
    irPara('historico', a)
    setChaveRecarga((k) => k + 1)
    if (window.innerWidth < 1024) setSidebarAberta(false)
    if (window.innerWidth < 1280) setCarteiraAberta(false)
  }

  function abrirImport(arquivo?: File) {
    setArquivoImport(arquivo ?? null)
    setImportAberto(true)
  }

  // Callbacks estáveis: o modal os guarda em ref, mas não há por que recriá-los
  // a cada token do streaming.
  const fecharImport = useCallback(() => setImportAberto(false), [])
  const aoImportar = useCallback(() => {
    // O preview vai para o chat: é lá que o consultor mostra e pede o "sim".
    irPara('chat')
    enviarOuEnfileirar('Importe o extrato que acabei de enviar.')
  }, [enviarOuEnfileirar, irPara])

  function perguntar(texto: string) {
    irPara('chat')
    if (window.innerWidth < 1280) setCarteiraAberta(false)
    enviarOuEnfileirar(texto)
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
              ativaId={tela === 'chat' ? ativa.id : ''}
              historicoAtivo={tela === 'historico'}
              onSelecionar={selecionar}
              onNova={criarConversa}
              onExcluir={excluir}
              onFechar={() => setSidebarAberta(false)}
              onImportar={() => abrirImport()}
              onAbrirCarteira={abrirCarteira}
              onAbrirHistorico={() => abrirHistorico()}
            />
          </div>
        </>
      )}

      {tela === 'historico' ? (
        <TelaHistorico
          aba={aba}
          onAba={(a) => irPara('historico', a)}
          sidebarAberta={sidebarAberta}
          onAbrirSidebar={() => setSidebarAberta(true)}
          chaveRecarga={chaveRecarga}
          onPerguntar={perguntar}
          onImportar={abrirImport}
        />
      ) : (
        <ChatView
          conversa={ativa}
          ocupado={ocupado}
          streamingId={streamingId}
          toolsRodando={toolsRodando}
          sidebarAberta={sidebarAberta}
          carteiraAberta={carteiraAberta}
          rascunho={rascunho}
          onRascunho={setRascunho}
          onAbrirSidebar={() => setSidebarAberta(true)}
          onAlternarCarteira={() =>
            carteiraAberta ? setCarteiraAberta(false) : abrirCarteira()
          }
          onEnviar={(t) => void enviar(t)}
          onParar={parar}
          onImportar={() => abrirImport()}
        />
      )}

      {carteiraAberta && tela === 'chat' && (
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
              onPerguntar={perguntar}
              onAbrirHistorico={() => abrirHistorico()}
              chaveRecarga={chaveRecarga}
            />
          </div>
        </>
      )}

      <ModalImport
        aberto={importAberto}
        arquivoInicial={arquivoImport}
        onFechar={fecharImport}
        onImportado={aoImportar}
      />
    </div>
  )
}
