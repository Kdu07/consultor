// ── Tipos espelhando os endpoints do FastAPI ────────────────────────────────

export type Classe =
  | 'ACAO'
  | 'FII'
  | 'ETF'
  | 'BDR'
  | 'RF'
  | 'TESOURO'
  | 'FUNDO'
  | 'CAIXA'

export interface Posicao {
  id: number
  ticker: string | null
  nome: string
  classe: Classe
  quantidade: number
  preco_medio: number | null
  valor: number
  percentual: number
  source: string
  as_of: string | null
  is_live: boolean
}

export interface ClasseAlocacao {
  classe: Classe
  valor: number
  percentual_atual: number
  percentual_alvo: number
  desvio_pp: number | null
  fora_da_banda: boolean | null
}

export interface Dashboard {
  total: number
  fracao_ao_vivo_pct: number
  fracao_extrato_pct: number
  as_of_mais_antigo: string | null
  data_ultima_atualizacao_posicoes: string | null
  ultimo_snapshot: { data: string; valor_total: number } | null
  posicoes: Posicao[]
  por_classe: ClasseAlocacao[]
  tem_alvos: boolean
  tem_alvos_ativo: boolean
  data_hora: string
}

export interface Sugestao {
  acao: 'REDUZIR' | 'AUMENTAR'
  nivel: 'classe' | 'ativo'
  ativo?: string
  classe?: string
  razao: string
  valor_a_mover: number
  desvio_pp: number
}

export interface Rebalanceamento {
  status?: string
  total_sugestoes?: number
  data_analise?: string
  snapshot?: { as_of_mais_antigo?: string | null }
  sugestoes_por_classe?: Sugestao[]
  sugestoes_por_ativo?: Sugestao[]
  nota_alvos_ativo?: string
  error?: string
}

export interface Snapshot {
  id: number
  data_referencia: string
  valor_total: number
  posicoes_count: number
  criado_em: string
}

export interface PreviewExtrato {
  total_posicoes: number
  total_valor_mercado: number
  data_referencia: string
  checagem_totais?: { ok?: boolean; aviso?: string }
  proventos_do_mes?: { quantidade?: number; total_liquido?: number }
  linhas_ignoradas?: unknown[]
}

// ── Fetch helpers ───────────────────────────────────────────────────────────

async function getJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json() as Promise<T>
}

export const getDashboard = () => getJSON<Dashboard>('/dashboard')
export const getRebalanceamento = () =>
  getJSON<Rebalanceamento>('/rebalanceamento')
export const getSnapshots = () => getJSON<Snapshot[]>('/snapshots')

export async function criarSnapshot(): Promise<Snapshot> {
  const resp = await fetch('/snapshots', { method: 'POST' })
  if (!resp.ok) {
    const erro = await resp.json().catch(() => null)
    throw new Error(erro?.detail ?? `HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function enviarExtrato(arquivo: File): Promise<PreviewExtrato> {
  const form = new FormData()
  form.append('arquivo', arquivo)
  const resp = await fetch('/extrato/upload', { method: 'POST', body: form })
  const data = await resp.json().catch(() => null)
  if (!resp.ok) {
    throw new Error(data?.detail ?? 'Não consegui ler o extrato.')
  }
  return data as PreviewExtrato
}

export async function limparSessao(sessionId: string): Promise<void> {
  await fetch(`/chat/${sessionId}`, { method: 'DELETE' }).catch(() => {})
}

// ── Chat em streaming (SSE sobre POST) ──────────────────────────────────────

export interface DoneEvent {
  reply: string
  tokens_input: number
  tokens_output: number
  iterations: number
  cost_usd: number
  anomaly: boolean
}

export interface StreamHandlers {
  onText(delta: string): void
  onTools(names: string[]): void
  onToolsDone(names: string[]): void
  onDone(evento: DoneEvent): void
  onError(mensagem: string): void
}

/**
 * Consome POST /chat/stream. EventSource não faz POST, então lemos o corpo à
 * mão: o protocolo SSE aqui é só uma sequência de blocos `data: {...}\n\n`.
 */
export async function streamChat(
  message: string,
  sessionId: string,
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal,
    })
  } catch (e) {
    // Parar antes de a resposta começar também cai aqui — e não é uma falha.
    if ((e as Error)?.name !== 'AbortError') {
      h.onError('Não consegui falar com o servidor.')
    }
    return
  }

  if (!resp.ok || !resp.body) {
    h.onError(`O servidor respondeu ${resp.status}.`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Um evento termina em linha em branco; o resto fica no buffer.
      let corte: number
      while ((corte = buffer.indexOf('\n\n')) !== -1) {
        const bruto = buffer.slice(0, corte)
        buffer = buffer.slice(corte + 2)
        despachar(bruto, h)
      }
    }
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') return
    h.onError('A conexão caiu no meio da resposta.')
  }
}

function despachar(bloco: string, h: StreamHandlers): void {
  const linhas = bloco.split('\n').filter((l) => l.startsWith('data:'))
  if (linhas.length === 0) return
  const json = linhas.map((l) => l.slice(5).trim()).join('')
  if (!json) return

  let ev: Record<string, unknown>
  try {
    ev = JSON.parse(json)
  } catch {
    return
  }

  switch (ev.type) {
    case 'text':
      h.onText(String(ev.text ?? ''))
      break
    case 'tools':
      h.onTools((ev.names as string[]) ?? [])
      break
    case 'tools_done':
      h.onToolsDone((ev.names as string[]) ?? [])
      break
    case 'done':
      h.onDone(ev as unknown as DoneEvent)
      break
  }
}
