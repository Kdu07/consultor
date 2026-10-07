import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, MessageSquareText, RefreshCw } from 'lucide-react'
import {
  getDesempenho,
  urlExportCSV,
  type Desempenho,
  type JanelaTipo,
  type MesDesempenho,
} from '../../lib/api'
import {
  fmtBRL,
  fmtBRLCompacto,
  fmtDataHora,
  fmtMes,
  fmtMesLongo,
  fmtPctSinal,
} from '../../lib/format'
import { mesAnterior, mesesEntre } from '../../lib/graficos'
import Card from '../dashboard/Card'
import BannerPendencias from './BannerPendencias'
import ComposicaoCarteira from './ComposicaoCarteira'
import GraficoColunas from './GraficoColunas'
import GraficoLinhas from './GraficoLinhas'
import KpiJanela from './KpiJanela'
import RendaPassiva from './RendaPassiva'
import TabelaMensal from './TabelaMensal'

interface Props {
  chaveRecarga: number
  onIrExtratos(): void
  onPerguntar(texto: string): void
}

type Recorte = Exclude<JanelaTipo, 'mes'>

const RECORTES: { id: Recorte; rotulo: string }[] = [
  { id: '12m', rotulo: '12 meses' },
  { id: 'ano', rotulo: 'No ano' },
  { id: 'inicio', rotulo: 'Desde o início' },
]

// Cores: a carteira é o assunto (tinta mais clara); CDI e IPCA são contexto, em
// cinza, separados pelo tracejado e pela legenda. As cores categóricas ficam
// para as classes — não se reaproveita o azul das Ações para "a carteira".
const COR_CARTEIRA = 'var(--color-ink)'
const COR_REFERENCIA = 'var(--color-ink-3)'

const considerado = (m?: MesDesempenho) =>
  !!m && (m.status === 'ok' || m.status === 'provisorio') && m.rentabilidade_pct != null

export default function AbaDesempenho({ chaveRecarga, onIrExtratos, onPerguntar }: Props) {
  const [dados, setDados] = useState<Desempenho | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [recorte, setRecorte] = useState<Recorte>('12m')

  const carregar = useCallback(async () => {
    setCarregando(true)
    setErro(null)
    try {
      setDados(await getDesempenho())
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => {
    void carregar()
  }, [carregar, chaveRecarga])

  const porMes = useMemo(
    () => new Map((dados?.meses ?? []).map((m) => [m.mes, m])),
    [dados],
  )

  // Meses do recorte, sem os meses iniciais em que ainda não havia histórico:
  // a janela de 12 meses de quem começou em março não desenha oito meses vazios.
  const mesesRecorte = useMemo(() => {
    const j = dados?.janelas[recorte]
    if (!j?.de || !j.ate) return []
    const todos = mesesEntre(j.de, j.ate)
    const primeiro = todos.findIndex((m) => porMes.has(m) && porMes.get(m)!.status !== 'lacuna')
    return primeiro === -1 ? [] : todos.slice(primeiro)
  }, [dados, recorte, porMes])

  const acumulado = useMemo(() => {
    const inicio = mesesRecorte.findIndex((m) => considerado(porMes.get(m)))
    if (inicio === -1) return null
    const lista = mesesRecorte.slice(inicio)
    const rotulos = [mesAnterior(lista[0]), ...lista]
    const carteira: (number | null)[] = [0]
    const cdi: (number | null)[] = [0]
    const ipca: (number | null)[] = [0]
    const vazias: number[] = []
    let f = 1
    let fc = 1
    let fi = 1
    lista.forEach((mes, k) => {
      const m = porMes.get(mes)
      if (!considerado(m)) {
        carteira.push(null)
        cdi.push(null)
        ipca.push(null)
        vazias.push(k + 1)
        return
      }
      f *= 1 + m!.rentabilidade_pct! / 100
      carteira.push((f - 1) * 100)
      if (m!.cdi_pct != null) {
        fc *= 1 + m!.cdi_pct / 100
        cdi.push((fc - 1) * 100)
      } else cdi.push(null)
      if (m!.ipca_pct != null) {
        fi *= 1 + m!.ipca_pct / 100
        ipca.push((fi - 1) * 100)
      } else ipca.push(null)
    })
    return { rotulos, carteira, cdi, ipca, vazias }
  }, [mesesRecorte, porMes])

  if (carregando && !dados) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="shimmer h-40 rounded-xl" />
          ))}
        </div>
        <div className="shimmer h-72 rounded-xl" />
      </div>
    )
  }

  if (erro && !dados) {
    return (
      <Card>
        <p className="text-[13px] text-critical">Não consegui carregar o desempenho: {erro}</p>
      </Card>
    )
  }

  if (!dados || dados.vazio) {
    return (
      <Card>
        <div className="py-6 text-center">
          <p className="text-[15px] font-medium text-ink">Ainda não há histórico</p>
          <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-2">
            A rentabilidade sai dos extratos arquivados. Envie os meses antigos de uma vez na
            aba Extratos; o mês mais recente entra pelo botão "Importar extrato", no chat.
          </p>
          <button
            onClick={onIrExtratos}
            className="mt-4 rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition-all hover:brightness-110"
          >
            Enviar extratos
          </button>
        </div>
      </Card>
    )
  }

  const j = dados.janelas
  const meses = mesesRecorte.map((m) => porMes.get(m)!).filter(Boolean)
  const bench = dados.benchmarks

  return (
    <div className={`space-y-4 transition-opacity ${carregando ? 'opacity-60' : ''}`}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiJanela rotulo="Último mês" janela={j.mes} />
        <KpiJanela rotulo="No ano" janela={j.ano} />
        <KpiJanela rotulo="12 meses" janela={j['12m']} />
        <KpiJanela rotulo="Desde o início" janela={j.inicio} />
      </div>

      <BannerPendencias pendencias={dados.pendencias} onIrExtratos={onIrExtratos} />

      {/* Uma linha de filtro acima de tudo o que ela recorta */}
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Período dos gráficos" className="hairline flex rounded-lg bg-surface p-0.5">
          {RECORTES.map((r) => (
            <button
              key={r.id}
              role="radio"
              aria-checked={recorte === r.id}
              onClick={() => setRecorte(r.id)}
              className={`rounded-md px-3 py-1.5 text-[12.5px] transition-colors ${
                recorte === r.id ? 'bg-surface-3 text-ink' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {r.rotulo}
            </button>
          ))}
        </div>
        <button
          onClick={() => void carregar()}
          title="Atualizar"
          className="rounded-md p-2 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <RefreshCw size={14} className={carregando ? 'animate-spin' : ''} />
        </button>
        <button
          onClick={() =>
            onPerguntar(
              'Como foi o desempenho da minha carteira nos últimos 12 meses, comparado ao CDI e à inflação?',
            )
          }
          className="hairline ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <MessageSquareText size={14} />
          Pedir a análise ao consultor
        </button>
      </div>

      <Card titulo="Rentabilidade acumulada">
        {acumulado ? (
          <GraficoLinhas
            titulo="Rentabilidade acumulada da carteira, comparada ao CDI e ao IPCA"
            rotulos={acumulado.rotulos.map(fmtMes)}
            rotuloTooltip={(i) =>
              i === 0 ? `Início (fim de ${fmtMes(acumulado.rotulos[0])})` : fmtMesLongo(acumulado.rotulos[i])
            }
            series={[
              { id: 'carteira', rotulo: 'Carteira', cor: COR_CARTEIRA, destaque: true, valores: acumulado.carteira },
              { id: 'cdi', rotulo: 'CDI', cor: COR_REFERENCIA, valores: acumulado.cdi },
              { id: 'ipca', rotulo: 'IPCA', cor: COR_REFERENCIA, tracejado: true, valores: acumulado.ipca },
            ]}
            vazias={acumulado.vazias}
            comZero
            formatarValor={(v) => fmtPctSinal(v)}
            formatarEixo={(v) => fmtPctSinal(v, Math.abs(v) < 10 && v % 1 !== 0 ? 1 : 0)}
          />
        ) : (
          <p className="text-[13px] text-ink-3">
            Nenhum mês do período tem rentabilidade calculável ainda — veja o que falta acima.
          </p>
        )}
        <p className="mt-3 text-[11px] text-ink-3">
          Rentabilidade bruta, descontados aportes e resgates (Modified Dietz por mês, encadeada).
          CDI e IPCA acumulados nos mesmos meses; meses sem rentabilidade ficam sombreados e fora
          da conta.
          {bench?.status === 'indisponivel' && ' O BCB não respondeu agora — sem CDI e IPCA.'}
        </p>
      </Card>

      {meses.length > 0 && (
        <Card titulo="Patrimônio e aportes">
          <GraficoLinhas
            titulo="Patrimônio no fechamento de cada mês"
            rotulos={meses.map((m) => fmtMes(m.mes))}
            rotuloTooltip={(i) => fmtMesLongo(meses[i].mes)}
            series={[
              {
                id: 'patrimonio',
                rotulo: 'Patrimônio',
                cor: COR_CARTEIRA,
                destaque: true,
                valores: meses.map((m) => (m.status === 'lacuna' ? null : (m.patrimonio_fim ?? null))),
              },
            ]}
            formatarValor={fmtBRL}
            formatarEixo={(v) => fmtBRLCompacto(v)}
            altura={170}
          />
          <p className="mt-4 mb-1 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
            Aportes líquidos (aportes − resgates)
          </p>
          <GraficoColunas
            titulo="Aportes líquidos por mês"
            rotulos={meses.map((m) => fmtMes(m.mes))}
            valores={meses.map((m) => (considerado(m) ? (m.aportes_liquidos ?? 0) : null))}
            cor={COR_REFERENCIA}
            formatarValor={fmtBRL}
            formatarEixo={(v) => fmtBRLCompacto(v)}
            rotuloTooltip={(i) => fmtMesLongo(meses[i].mes)}
            detalheTooltip={(i) => {
              const m = meses[i]
              if (!considerado(m)) return <div className="text-[11px] text-ink-3">Sem os lançamentos da conta</div>
              return (
                <div className="mt-1 space-y-0.5 text-[11px] text-ink-3">
                  <div>aportes {fmtBRL(m.aportes)}</div>
                  <div>resgates {fmtBRL(m.resgates)}</div>
                </div>
              )
            }}
          />
        </Card>
      )}

      {meses.length > 0 && (
        <Card
          titulo="Mês a mês"
          acao={
            <a
              href={urlExportCSV('mensal', recorte)}
              download
              title="Exportar a tabela mês a mês (CSV para Excel)"
              className="hairline flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[12px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Download size={13} aria-hidden="true" />
              CSV
            </a>
          }
        >
          <TabelaMensal meses={meses} />
        </Card>
      )}

      <ComposicaoCarteira
        recorte={recorte}
        chaveRecarga={chaveRecarga}
        onMudouTotal={() => void carregar()}
      />

      <RendaPassiva proventos={dados.proventos} meses={mesesRecorte} />

      <p className="pb-2 text-[11px] text-ink-3">
        Fonte: {dados.fonte}. Calculado em {fmtDataHora(dados.gerado_em)}.
      </p>
    </div>
  )
}
