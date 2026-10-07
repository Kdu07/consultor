import { useCallback, useEffect, useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  ChartLine,
  Minus,
  RefreshCw,
  TriangleAlert,
  X,
} from 'lucide-react'
import Card from './Card'
import Sparkline from './Sparkline'
import BarraAlocacao from './BarraAlocacao'
import BulletsClasse from './BulletsClasse'
import TabelaPosicoes from './TabelaPosicoes'
import CardRebalanceamento from './CardRebalanceamento'
import {
  getDashboard,
  getHistoricoExtratos,
  getRebalanceamento,
  type Dashboard,
  type ExtratoResumo,
  type Rebalanceamento,
} from '../../lib/api'
import { fmtBRL, fmtData, fmtDataHora, fmtPct } from '../../lib/format'

interface Props {
  onFechar(): void
  onPerguntar(texto: string): void
  onAbrirHistorico(): void
  /** Muda quando algo externo (um import, por exemplo) exige recarregar. */
  chaveRecarga: number
}

export default function PainelCarteira({
  onFechar,
  onPerguntar,
  onAbrirHistorico,
  chaveRecarga,
}: Props) {
  const [dados, setDados] = useState<Dashboard | null>(null)
  const [rebal, setRebal] = useState<Rebalanceamento | null>(null)
  const [fechamentos, setFechamentos] = useState<ExtratoResumo[]>([])
  const [carregando, setCarregando] = useState(true)
  const [carregandoRebal, setCarregandoRebal] = useState(true)
  const [erro, setErro] = useState<string | null>(null)

  const carregar = useCallback(async () => {
    setCarregando(true)
    setErro(null)
    try {
      const d = await getDashboard()
      setDados(d)
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setCarregando(false)
    }

    // Rebalanceamento e histórico não bloqueiam o corpo do painel.
    setCarregandoRebal(true)
    getRebalanceamento()
      .then(setRebal)
      .catch(() => setRebal({ error: 'Não consegui analisar agora.' }))
      .finally(() => setCarregandoRebal(false))

    getHistoricoExtratos()
      .then(setFechamentos)
      .catch(() => setFechamentos([]))
  }, [])

  useEffect(() => {
    void carregar()
  }, [carregar, chaveRecarga])

  const vazia = !carregando && dados && dados.posicoes.length === 0

  // Δ contra o último fechamento de extrato. A base é a soma das posições daquele
  // extrato — a mesma do total ao vivo acima (nenhum dos dois conta valores em
  // trânsito). Variação de saldo, não rentabilidade: inclui aportes.
  const ultimo = dados?.ultimo_fechamento ?? null
  const delta =
    dados && ultimo && ultimo.valor_total > 0
      ? dados.total - ultimo.valor_total
      : null
  const deltaPct =
    delta !== null && ultimo ? (delta / ultimo.valor_total) * 100 : null

  // Série = os fechamentos mensais do extrato (decisão 2 do dono): o patrimônio
  // oficial do BTG em cada fim de mês.
  const serie = fechamentos
    .filter((f) => f.periodo_mensal && f.patrimonio !== null)
    .sort((a, b) => a.data_referencia.localeCompare(b.data_referencia))
    .map((f) => ({ rotulo: f.data_referencia, valor: f.patrimonio! }))

  return (
    <div className="flex h-full w-full flex-col bg-plane xl:w-[520px] xl:shrink-0 xl:border-l xl:border-white/7">
      <header className="flex h-12 shrink-0 items-center gap-2 px-4">
        <h2 className="flex-1 text-[13px] font-medium text-ink-2">Carteira</h2>
        <button
          onClick={() => void carregar()}
          title="Atualizar"
          className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <RefreshCw size={15} className={carregando ? 'animate-spin' : ''} />
        </button>
        <button
          onClick={onAbrirHistorico}
          title="Ver histórico e desempenho"
          className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <ChartLine size={15} />
        </button>
        <button
          onClick={onFechar}
          title="Fechar"
          className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <X size={15} />
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-6">
        {erro && (
          <Card>
            <p className="text-[13px] text-critical">
              Erro ao carregar a carteira: {erro}
            </p>
          </Card>
        )}

        {carregando && !dados && (
          <>
            <div className="shimmer h-32 rounded-xl" />
            <div className="shimmer h-40 rounded-xl" />
          </>
        )}

        {vazia && (
          <Card>
            <p className="text-[13px] text-ink-3">
              Carteira vazia. Importe um extrato do BTG para começar.
            </p>
          </Card>
        )}

        {dados && dados.posicoes.length > 0 && (
          <>
            {/* Hero + KPIs */}
            <Card>
              <p className="text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                Patrimônio total
              </p>
              <p
                className="mt-1 text-[clamp(30px,5vw,44px)] leading-none font-semibold"
                title="Estimativa ao vivo: soma das posições com cotações recentes quando há — sem valores em trânsito. Não é o número do extrato nem o do app BTG."
              >
                {fmtBRL(dados.total)}
              </p>
              <p className="mt-1 text-[11px] text-ink-3">
                estimativa ao vivo — soma das posições, sem valores em trânsito
              </p>

              {delta !== null && (
                <DeltaLinha
                  valor={delta}
                  pct={deltaPct}
                  referencia={ultimo!.data}
                />
              )}

              {ultimo?.saldo_liquido_btg != null && (
                <p
                  className="mt-1.5 text-[11px] text-ink-3"
                  title="Total Líquido do Sumário do extrato — é o número que o app do BTG costuma mostrar."
                >
                  Conferir com o app BTG — saldo líquido do extrato de{' '}
                  {fmtData(ultimo.data)}:{' '}
                  <span className="font-medium text-ink-2 tabular-nums">
                    {fmtBRL(ultimo.saldo_liquido_btg)}
                  </span>
                </p>
              )}

              {(ultimo?.validacao_veredito === 'erro' ||
                ultimo?.validacao_veredito === 'aviso') && (
                <p
                  className={`mt-1.5 flex items-center gap-1.5 text-[11px] ${
                    ultimo.validacao_veredito === 'erro'
                      ? 'text-critical'
                      : 'text-warn'
                  }`}
                  title="As conferências internas do último extrato não fecharam — abra o mês no histórico para ver os checks."
                >
                  <TriangleAlert size={12} className="shrink-0" aria-hidden="true" />
                  conferência do extrato com{' '}
                  {ultimo.validacao_veredito === 'erro' ? 'erro(s)' : 'aviso(s)'}
                </p>
              )}

              {serie.length >= 2 && (
                <button
                  onClick={onAbrirHistorico}
                  className="mt-3 block w-full text-left"
                  title="Ver o histórico completo"
                >
                  <Sparkline pontos={serie} />
                  <span className="mt-1 block text-[10.5px] text-ink-3">
                    fechamentos mensais — total bruto BTG, com valores em trânsito
                  </span>
                </button>
              )}

              <dl className="mt-3 grid grid-cols-3 gap-3 border-t border-line pt-3">
                <Kpi rotulo="Posições" valor={String(dados.posicoes.length)} />
                <Kpi
                  rotulo="Ao vivo"
                  valor={fmtPct(dados.fracao_ao_vivo_pct, 0)}
                />
                <Kpi
                  rotulo="Do extrato"
                  valor={fmtPct(dados.fracao_extrato_pct, 0)}
                />
              </dl>

              <p className="mt-3 text-[11px] text-ink-3">
                Atualizado em {fmtDataHora(dados.data_hora)}
              </p>
            </Card>

            <Card titulo="Alocação atual">
              <BarraAlocacao classes={dados.por_classe} total={dados.total} />
            </Card>

            {dados.tem_alvos && (
              <Card titulo="Atual vs. alvo">
                <BulletsClasse classes={dados.por_classe} />
              </Card>
            )}

            <CardRebalanceamento
              dados={rebal}
              carregando={carregandoRebal}
              onPerguntar={() =>
                onPerguntar(
                  'Analise minha carteira e me dê sugestões de rebalanceamento para este mês.',
                )
              }
            />

            <Card titulo={`Posições (${dados.posicoes.length})`}>
              <TabelaPosicoes posicoes={dados.posicoes} />
            </Card>
          </>
        )}
      </div>
    </div>
  )
}

function Kpi({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div>
      <dt className="text-[11px] text-ink-3">{rotulo}</dt>
      <dd className="text-[15px] font-medium tabular-nums">{valor}</dd>
    </div>
  )
}

function DeltaLinha({
  valor,
  pct,
  referencia,
}: {
  valor: number
  pct: number | null
  referencia: string
}) {
  const subiu = valor > 0
  const parado = Math.abs(valor) < 0.005
  const Icone = parado ? Minus : subiu ? ArrowUpRight : ArrowDownRight
  const cor = parado ? 'text-ink-3' : subiu ? 'text-good' : 'text-critical'

  return (
    <p className={`mt-2 flex items-center gap-1.5 text-[13px] ${cor}`}>
      <Icone size={14} className="shrink-0" />
      <span className="font-medium tabular-nums">
        {subiu && !parado ? '+' : ''}
        {fmtBRL(valor)}
        {pct !== null && !parado && ` (${pct > 0 ? '+' : ''}${pct.toFixed(1)}%)`}
      </span>
      <span className="text-ink-3">
        desde o fechamento de {fmtData(referencia)}
      </span>
    </p>
  )
}
