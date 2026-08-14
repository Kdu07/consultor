export interface MetaTurno {
  iteracoes: number
  tokensEntrada: number
  tokensSaida: number
  custoUsd: number
  anomalia: boolean
}

export interface Mensagem {
  id: string
  papel: 'user' | 'assistant'
  texto: string
  /** Tools usadas no turno, na ordem em que rodaram. */
  tools?: string[]
  meta?: MetaTurno
  erro?: boolean
}

export interface Conversa {
  id: string
  titulo: string
  criadaEm: number
  mensagens: Mensagem[]
}

const CHAVE = 'consultor.conversas.v1'

export function novoId(prefixo = 'c'): string {
  return `${prefixo}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export function novaConversa(): Conversa {
  return {
    id: novoId('sess'),
    titulo: 'Nova conversa',
    criadaEm: Date.now(),
    mensagens: [],
  }
}

export function tituloDe(texto: string): string {
  const limpo = texto.trim().replace(/\s+/g, ' ')
  return limpo.length > 42 ? `${limpo.slice(0, 42)}…` : limpo || 'Nova conversa'
}

/**
 * O histórico do agente vive na memória do servidor, indexado pelo id da
 * conversa; aqui guardamos só o que a UI precisa desenhar. Se o uvicorn
 * reiniciar, as mensagens continuam na tela mas o agente recomeça sem contexto.
 */
export function carregarConversas(): Conversa[] {
  try {
    const bruto = localStorage.getItem(CHAVE)
    if (!bruto) return []
    const dados = JSON.parse(bruto)
    return Array.isArray(dados) ? (dados as Conversa[]) : []
  } catch {
    return []
  }
}

export function salvarConversas(conversas: Conversa[]): void {
  try {
    // Mantém as 40 mais recentes — o localStorage tem teto de alguns MB.
    localStorage.setItem(CHAVE, JSON.stringify(conversas.slice(0, 40)))
  } catch {
    /* quota estourada: seguir sem persistir é melhor que quebrar a UI */
  }
}

export function agruparPorPeriodo(
  conversas: Conversa[],
): { rotulo: string; itens: Conversa[] }[] {
  const agora = new Date()
  const inicioHoje = new Date(
    agora.getFullYear(),
    agora.getMonth(),
    agora.getDate(),
  ).getTime()
  const inicioOntem = inicioHoje - 86_400_000
  const inicioSemana = inicioHoje - 7 * 86_400_000

  const grupos: { rotulo: string; itens: Conversa[] }[] = [
    { rotulo: 'Hoje', itens: [] },
    { rotulo: 'Ontem', itens: [] },
    { rotulo: 'Últimos 7 dias', itens: [] },
    { rotulo: 'Mais antigas', itens: [] },
  ]

  for (const c of conversas) {
    if (c.criadaEm >= inicioHoje) grupos[0].itens.push(c)
    else if (c.criadaEm >= inicioOntem) grupos[1].itens.push(c)
    else if (c.criadaEm >= inicioSemana) grupos[2].itens.push(c)
    else grupos[3].itens.push(c)
  }

  return grupos.filter((g) => g.itens.length > 0)
}
