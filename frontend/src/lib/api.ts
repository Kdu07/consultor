// ── Tipos espelhando os endpoints do FastAPI ────────────────────────────────

export type Classe =
  | 'ACAO'
  | 'FII'
  | 'ETF'
  | 'BDR'
  | 'RF'
  | 'TESOURO'
  | 'FUNDO'
  | 'CRIPTO'
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
  /**
   * Último extrato arquivado: a base do "desde o fechamento" do painel.
   * Três grandezas distintas, nunca intercambiáveis:
   *   valor_posicoes    — Σ posições, sem valores em trânsito (= valor_total)
   *   patrimonio_bruto  — Total Bruto do Sumário, com trânsito
   *   saldo_liquido_btg — Total Líquido do Sumário: o nº que o app BTG mostra
   * Opcionais: payloads v1/v2 não os têm (chegam null/ausentes).
   */
  ultimo_fechamento: {
    data: string
    valor_total: number
    valor_posicoes?: number | null
    patrimonio_bruto?: number | null
    saldo_liquido_btg?: number | null
    validacao_veredito?: string | null
  } | null
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

// ── Validação do extrato (app/tools/extrato_validacao.py) ──────────────────

export type VereditoValidacao = 'ok' | 'aviso' | 'erro'

/** Resumo compacto que preview de import e itens de lote carregam. */
export interface ResumoValidacao {
  veredito: VereditoValidacao
  erros: string[]
  avisos: string[]
  n_checks_ok: number
}

export interface CheckValidacao {
  id: string
  rotulo: string
  severidade: 'ok' | 'aviso' | 'erro' | 'nao_avaliavel'
  esperado: number | null
  obtido: number | null
  diferenca: number | null
  detalhe: string
}

/** Contrato congelado do validador — `validacao` irmã de `checagem` no payload. */
export interface ValidacaoExtrato {
  versao_validador: number
  veredito: VereditoValidacao
  checks: CheckValidacao[]
  erros: string[]
  avisos: string[]
  tolerancias?: { ok: number; erro: number }
}

export interface PeriodoExtrato {
  inicio: string | null
  fim: string
  mensal: boolean
}

export interface PreviewExtrato {
  total_posicoes: number
  total_valor_mercado: number
  data_referencia: string
  checagem_totais?: { ok?: boolean; aviso?: string }
  proventos_do_mes?: { quantidade?: number; total_liquido?: number }
  linhas_ignoradas?: unknown[]
  /** Opcionais: uploads anteriores ao validador não os trazem. */
  validacao?: ResumoValidacao | null
  periodo?: PeriodoExtrato | null
  /** As três grandezas do extrato recém-lido (mesmo vocabulário do dashboard). */
  patrimonio?: {
    valor_posicoes?: number | null
    patrimonio_bruto?: number | null
    saldo_liquido_btg?: number | null
    nota?: string
  } | null
}

// ── Histórico: desempenho (GET /desempenho) ────────────────────────────────

export type JanelaTipo = 'mes' | 'ano' | '12m' | 'inicio'

/** O mesmo vocabulário do motor (app/tools/desempenho.py). */
export type StatusMes =
  | 'ok'
  | 'provisorio'
  | 'sem_lancamentos'
  | 'sem_base'
  | 'periodo_parcial'
  | 'lacuna'

export interface ProventosDoMes {
  total: number
  proventos: number
  aluguel: number
  amortizacao: number
  quantidade: number
  por_classe: Record<string, number>
}

export interface MesDesempenho {
  mes: string
  status: StatusMes
  motivos: string[]
  avisos: string[]
  data_referencia?: string
  data_ini?: string | null
  data_fim?: string | null
  patrimonio_ini?: number | null
  patrimonio_fim?: number | null
  patrimonio_posicoes_fim?: number | null
  variacao_saldo?: number | null
  aportes?: number
  resgates?: number
  aportes_liquidos?: number
  nao_classificados?: number
  ganho?: number | null
  rentabilidade_pct?: number | null
  cdi_pct?: number | null
  ipca_pct?: number | null
  pct_do_cdi?: number | null
  retorno_real_pct?: number | null
  proventos?: ProventosDoMes
}

export interface JanelaDesempenho {
  tipo: JanelaTipo
  de: string | null
  ate: string | null
  meses: number
  considerados: string[]
  faltantes: string[]
  parcial: boolean
  provisorio: boolean
  rentabilidade_pct: number | null
  ganho: number | null
  aportes_liquidos: number | null
  patrimonio_ini: number | null
  patrimonio_fim: number | null
  cdi_pct: number | null
  pct_do_cdi: number | null
  ipca_pct: number | null
  retorno_real_pct: number | null
  cdi_pendente: string[]
  ipca_pendente: string[]
  anualizado_pct: number | null
}

export interface ProventoAtivo {
  chave: string
  ticker: string
  classe: string
  total: number
  pagamentos: number
  valor_atual: number | null
  yield_pct: number | null
  yield_sobre_custo_pct: number | null
}

export interface Desempenho {
  vazio: boolean
  ultimo_fechamento?: string
  meses: MesDesempenho[]
  janelas: Partial<Record<JanelaTipo, JanelaDesempenho>>
  proventos: {
    por_mes: (ProventosDoMes & { mes: string })[]
    ultimos_12m: {
      total: number
      meses_com_dado: number
      parcial: boolean
      yield_pct: number | null
    } | null
    por_ativo_12m: ProventoAtivo[]
  }
  pendencias: {
    nao_classificados: number
    valor_nao_classificado: number
    meses_sem_lancamentos: string[]
    meses_faltantes: string[]
    meses_razao_nao_fecha: string[]
    periodos_parciais: string[]
    /**
     * Frases prontas ("O fechamento de X não bate com a abertura de Y…") para os
     * meses em que a série não encadeia. Opcional: backend antigo não manda.
     */
    quebras_continuidade?: string[]
  }
  benchmarks?: {
    status: 'ok' | 'parcial' | 'indisponivel'
    cdi_ate: string | null
    ipca_ate: string | null
    erro: string | null
  }
  gerado_em?: string
  fonte?: string
}

export const getDesempenho = () => requisitar<Desempenho>('/desempenho')

// ── Desempenho: composição por classe e por ativo ───────────────────────────

/** Status de um papel ou classe numa janela (num mês só, não há 'parcial'). */
export type StatusComposicao = 'ok' | 'estimado' | 'parcial' | 'pendente' | 'sem_base' | 'indisponivel'

export interface ClasseComposicao {
  classe: string
  valor_ini: number | null
  valor_fim: number | null
  compras: number
  vendas: number
  renda: number
  resultado: number | null
  rentabilidade_pct: number | null
  meses: number
  meses_com_numero: number
  status: StatusComposicao
  peso_fim_pct: number | null
}

export interface AtivoComposicao extends ClasseComposicao {
  chave: string
  ticker: string | null
  nome: string | null
  quantidade_fim?: number
}

export interface PendenciaAtivo {
  mes: string
  data_referencia: string
  chave: string
  ticker: string | null
  nome: string | null
  classe: string
  quantidade_ini: number
  quantidade_fim: number
  preco_ini: number | null
  preco_fim: number | null
  pendencia: string
}

export interface Conciliacao {
  ganho_total: number
  ativos: number
  rendimento_caixa: number
  custos: number
  outros: number
  renda_sem_papel: number
  transito: number
  residuo: number
  meses_conferidos: number
}

export interface Composicao {
  vazio: boolean
  janela: {
    tipo: JanelaTipo
    de: string | null
    ate: string | null
    meses?: number
    lacunas?: string[]
    sem_mes_anterior?: string[]
  }
  meses?: string[]
  classes?: ClasseComposicao[]
  ativos?: AtivoComposicao[]
  caixa?: { valor_fim: number; peso_fim_pct: number | null; rendimento: number; custos: number } | null
  conciliacao?: Conciliacao | null
  avisos?: string[]
  pendencias?: PendenciaAtivo[]
  total_fim?: number | null
}

export interface MesDoAtivo {
  mes: string
  data_referencia: string
  /** null quando o mês não tem o extrato anterior (status sem_base). */
  quantidade_ini: number | null
  quantidade_fim: number
  preco_ini: number | null
  preco_fim: number | null
  valor_ini: number | null
  valor_fim: number | null
  compras: number
  vendas: number
  renda: number
  resultado: number | null
  rentabilidade_pct: number | null
  status: StatusComposicao
  pendencia: string | null
  aviso: string | null
}

export interface HistoricoAtivo {
  chave: string
  janela: { tipo: JanelaTipo; de: string; ate: string }
  meses: MesDoAtivo[]
  acumulado: AtivoComposicao
}

export const getComposicao = (janela: JanelaTipo) =>
  requisitar<Composicao>(`/desempenho/composicao?janela=${janela}`)
export const getHistoricoAtivo = (chave: string, janela: JanelaTipo) =>
  requisitar<HistoricoAtivo>(
    `/desempenho/ativo?chave=${encodeURIComponent(chave)}&janela=${janela}`,
  )
/** Download direto pelo navegador (o cookie de sessão vai junto). */
export const urlExportCSV = (tipo: 'mensal' | 'ativos', janela: JanelaTipo) =>
  `/desempenho/export.csv?tipo=${tipo}&janela=${janela}`

// ── Comparar dois fechamentos ───────────────────────────────────────────────

export interface LinhaComparacao {
  chave: string
  ticker: string | null
  nome: string | null
  classe: string
  quantidade_de: number | null
  quantidade_ate: number | null
  valor_de: number | null
  valor_ate: number | null
  variacao: number | null
}

export interface Comparacao {
  de: string
  ate: string
  posicoes: {
    entraram: LinhaComparacao[]
    sairam: LinhaComparacao[]
    mudaram: LinhaComparacao[]
    mantidos: LinhaComparacao[]
  }
  classes: {
    classe: string
    valor_de: number
    valor_ate: number
    peso_de: number | null
    peso_ate: number | null
  }[]
  total_de: number
  total_ate: number
  periodo: {
    meses: string[]
    considerados: string[]
    faltantes: string[]
    provisorio: boolean
    rentabilidade_pct: number | null
    ganho: number | null
    aportes_liquidos: number | null
    proventos: number
  }
}

export const compararMeses = (de: string, ate: string) =>
  requisitar<Comparacao>(`/extrato/comparar?de=${de}&ate=${ate}`)

// ── Histórico: extratos arquivados ──────────────────────────────────────────

export interface ExtratoResumo {
  id: number
  data_referencia: string
  arquivo: string | null
  total_posicoes: number
  total_valor_mercado: number
  proventos_total: number
  proventos_quantidade: number
  importado_em: string
  atualizado_em: string
  mes: string | null
  /** Total Bruto do Sumário (com valores em trânsito). */
  patrimonio: number | null
  periodo_mensal: boolean
  status: StatusMes | null
  tem_lancamentos: boolean
  lancamentos: number
  nao_classificados: number
  checagem_ok: boolean | null
  checagem_conta_ok: boolean | null
  /** É o mês que a carteira reflete — não pode ser excluído. */
  protegido: boolean
  /** Veredito do validador ('ok' | 'aviso' | 'erro'); null em payloads v1/v2. */
  validacao_veredito?: string | null
  /** Quantos checks reprovaram com erro; 0/null em payloads antigos. */
  validacao_erros?: number | null
}

export interface PosicaoArquivada {
  ticker: string | null
  nome: string
  classe: string
  quantidade: number
  preco_medio: number | null
  valor_mercado: number
  vencimento?: string | null
  taxa_contratada?: string | null
  chave_externa?: string | null
}

export interface MovimentoArquivado {
  data: string | null
  transacao: string
  ticker: string | null
  quantidade: number | null
  valor_bruto: number | null
  valor_liquido: number | null
  classe?: string | null
}

export interface ExtratoDetalhe extends ExtratoResumo {
  extrato: {
    posicoes: PosicaoArquivada[]
    proventos: MovimentoArquivado[]
    movimentacoes: MovimentoArquivado[]
    valores_em_transito: { data_liquidacao: string | null; descricao: string; valor: number }[]
    checagem: {
      ok?: boolean
      aviso?: string
      total_parseado?: number
      total_esperado?: number
      diferenca?: number
      conta_corrente?: { ok?: boolean | null; aviso?: string; diferenca?: number }
    }
    sumario?: { meta?: { periodo_inicio?: string | null } }
    /** Irmã de `checagem` no payload v3+; payloads antigos não a têm. */
    validacao?: ValidacaoExtrato | null
  }
}

export interface Lancamento {
  seq: number
  data: string | null
  descricao: string
  valor: number
  saldo: number | null
  tipo: string
  rotulo: string
  externo: boolean
  origem: 'linha' | 'regra' | 'padrao' | 'nenhuma'
  regra_id: number | null
  padrao_sugerido: string
}

export interface LancamentosMes {
  data_referencia: string
  tem_lancamentos: boolean
  saldo_inicial: number | null
  checagem: { ok?: boolean | null; aviso?: string; diferenca?: number } | null
  lancamentos: Lancamento[]
}

export const getHistoricoExtratos = () =>
  requisitar<ExtratoResumo[]>('/extrato/historico')
export const getExtratoDetalhe = (data: string) =>
  requisitar<ExtratoDetalhe>(`/extrato/historico/${data}`)
export const getLancamentos = (data: string) =>
  requisitar<LancamentosMes>(`/extrato/historico/${data}/lancamentos`)
export const excluirMes = (data: string) =>
  requisitar<void>(`/extrato/historico/${data}`, { method: 'DELETE' })

// ── Regras de classificação dos lançamentos ─────────────────────────────────

export interface RegraEntrada {
  tipo: string
  escopo: 'texto' | 'linha' | 'ativo_mes'
  modo?: 'exato' | 'prefixo' | 'contem'
  padrao?: string
  sinal?: 'credito' | 'debito' | null
  data_referencia?: string
  seq?: number
  /** Escopo ativo_mes: a chave do papel (B3:TAEE11, TD:LFT:2031-03-01...). */
  chave?: string
}

export interface Regra {
  id: number
  escopo: 'texto' | 'linha' | 'ativo_mes'
  modo: string
  padrao: string
  sinal: string | null
  data_referencia: string | null
  seq: number | null
  tipo: string
  rotulo: string
  criado_em: string
  atualizado_em: string
}

export const listarRegras = () => requisitar<Regra[]>('/extrato/regras')
export const criarRegra = (r: RegraEntrada) =>
  postJSON<{ regra: Regra; nova: boolean; afetados: { meses: number; lancamentos: number } }>(
    '/extrato/regras',
    r,
  )
export const excluirRegra = (id: number) =>
  requisitar<void>(`/extrato/regras/${id}`, { method: 'DELETE' })

// ── Lote de extratos antigos ────────────────────────────────────────────────

export type StatusItemLote =
  | 'novo'
  | 'substitui'
  | 'reenvio_do_atual'
  | 'diverge_da_carteira'
  | 'mais_novo_que_carteira'
  | 'periodo_nao_mensal'
  | 'duplicado_no_lote'
  | 'erro'

export interface ItemLote {
  arquivo: string
  data_referencia: string | null
  status: StatusItemLote
  selecionavel: boolean
  selecionado_padrao: boolean
  patrimonio: number | null
  total_posicoes: number | null
  lancamentos: number | null
  nao_classificados: number | null
  checagem_ok: boolean | null
  checagem_conta_ok: boolean | null
  rentabilidade_pct: number | null
  completa_lancamentos: boolean
  mensagem: string | null
  avisos: string[]
  /** Resumo do validador; ausente em lotes avaliados antes dele. */
  validacao?: ResumoValidacao | null
}

export interface Lote {
  id: string
  criado_em: string
  data_corte: string | null
  itens: ItemLote[]
}

export interface ResultadoLote {
  arquivados: { data_referencia: string; acao: 'criado' | 'atualizado' }[]
  recusados: { data_referencia: string; motivo: string; mensagem: string | null }[]
  carteira_alterada: false
}

export function enviarLote(arquivos: File[]): Promise<Lote> {
  const form = new FormData()
  for (const a of arquivos) form.append('arquivos', a)
  return requisitar<Lote>('/extrato/lote', { method: 'POST', body: form })
}

export const confirmarLote = (id: string, datas: string[]) =>
  postJSON<ResultadoLote>(`/extrato/lote/${id}/confirmar`, { datas })

export async function descartarLote(id: string): Promise<void> {
  await requisitar<void>(`/extrato/lote/${id}`, { method: 'DELETE' }).catch(() => {})
}

// ── Sessão ──────────────────────────────────────────────────────────────────

export interface AuthStatus {
  auth_required: boolean
  authenticated: boolean
}

/**
 * Um cookie expirado só aparece quando alguma chamada volta 401 — daí este
 * gancho, que o App usa para voltar à tela de senha de onde quer que seja.
 */
let aoPerderSessao: (() => void) | null = null

export function definirHandlerNaoAutenticado(fn: () => void): void {
  aoPerderSessao = fn
}

function checar401(status: number): boolean {
  if (status !== 401) return false
  aoPerderSessao?.()
  return true
}

export const getAuthStatus = () => getJSON<AuthStatus>('/auth/status')

export async function fazerLogin(senha: string): Promise<void> {
  const resp = await fetch('/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ senha }),
  })
  if (!resp.ok) {
    const erro = await resp.json().catch(() => null)
    throw new Error(erro?.detail ?? `HTTP ${resp.status}`)
  }
}

export async function fazerLogout(): Promise<void> {
  await fetch('/logout', { method: 'POST' }).catch(() => {})
}

// ── Fetch helpers ───────────────────────────────────────────────────────────

async function getJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) {
    checar401(resp.status)
    throw new Error(`HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

/**
 * fetch + 401 + a mensagem do backend. O FastAPI devolve o motivo em `detail`
 * (texto nos erros da aplicação, lista nos 422 de validação).
 */
async function requisitar<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  if (!resp.ok) {
    checar401(resp.status)
    const erro = await resp.json().catch(() => null)
    const detalhe = erro?.detail
    throw new Error(typeof detalhe === 'string' ? detalhe : `HTTP ${resp.status}`)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

function postJSON<T>(url: string, corpo: unknown): Promise<T> {
  return requisitar<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
  })
}

export const getDashboard = () => getJSON<Dashboard>('/dashboard')
export const getRebalanceamento = () =>
  getJSON<Rebalanceamento>('/rebalanceamento')

export async function enviarExtrato(arquivo: File): Promise<PreviewExtrato> {
  const form = new FormData()
  form.append('arquivo', arquivo)
  const resp = await fetch('/extrato/upload', { method: 'POST', body: form })
  const data = await resp.json().catch(() => null)
  if (!resp.ok) {
    checar401(resp.status)
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
    if (checar401(resp.status)) {
      h.onError('Sua sessão expirou — entre de novo.')
      return
    }
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
