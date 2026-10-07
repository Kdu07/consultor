import { useEffect, useState } from 'react'
import { CircleAlert, Download, TriangleAlert } from 'lucide-react'
import {
  criarRegra,
  getComposicao,
  urlExportCSV,
  type Composicao,
  type JanelaTipo,
  type PendenciaAtivo,
} from '../../lib/api'
import { fmtBRL, fmtBRLSinal, fmtMes, fmtQtde } from '../../lib/format'
import Card from '../dashboard/Card'
import { useToast } from '../Toasts'
import TabelaAtivos from './TabelaAtivos'
import TabelaClasses from './TabelaClasses'

type Recorte = Exclude<JanelaTipo, 'mes'>

interface Props {
  /** O período escolhido no filtro de cima — a composição acompanha. */
  recorte: Recorte
  chaveRecarga: number
  /** Uma regra de ativo pode mudar o total (transferência vira aporte): recarregar tudo. */
  onMudouTotal(): void
}

const NOTAS: Record<string, string> = {
  sem_lancamentos:
    'Há arquivos antigos, sem os lançamentos da conta: cupons e resgates de títulos desses meses ficam de fora — reenvie os XLSX.',
  renda_sem_papel: 'Parte da renda caiu na conta sem dizer de qual papel: entra no total, não num papel.',
  resgate_sem_titulo: 'Um resgate de renda fixa não disse de qual título — ficou fora dos papéis.',
}

export default function ComposicaoCarteira({ recorte, chaveRecarga, onMudouTotal }: Props) {
  const toast = useToast()
  const [soUltimoMes, setSoUltimoMes] = useState(false)
  const [dados, setDados] = useState<Composicao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [versao, setVersao] = useState(0)
  const janela: JanelaTipo = soUltimoMes ? 'mes' : recorte

  useEffect(() => {
    let vivo = true
    setErro(null)
    getComposicao(janela)
      .then((d) => vivo && setDados(d))
      .catch((e: Error) => vivo && setErro(e.message))
    return () => {
      vivo = false
    }
  }, [janela, chaveRecarga, versao])

  async function resolver(p: PendenciaAtivo, tipo: string) {
    try {
      await criarRegra({ tipo, escopo: 'ativo_mes', data_referencia: p.data_referencia, chave: p.chave })
      toast('ok', `${p.ticker ?? p.nome ?? p.chave} em ${fmtMes(p.mes)}: anotado.`)
      setVersao((v) => v + 1)
      if (tipo !== 'EVENTO_SOCIETARIO') onMudouTotal()
    } catch (e) {
      toast('erro', (e as Error).message)
    }
  }

  const acao = (
    <div className="flex items-center gap-2">
      <div role="radiogroup" aria-label="Período da composição" className="hairline flex rounded-lg bg-surface p-0.5">
        {[
          { id: false, rotulo: 'Mesmo período' },
          { id: true, rotulo: 'Último mês' },
        ].map((o) => (
          <button
            key={o.rotulo}
            role="radio"
            aria-checked={soUltimoMes === o.id}
            onClick={() => setSoUltimoMes(o.id)}
            className={`rounded-md px-2.5 py-1 text-[12px] normal-case transition-colors ${
              soUltimoMes === o.id ? 'bg-surface-3 text-ink' : 'text-ink-3 hover:text-ink-2'
            }`}
          >
            {o.rotulo}
          </button>
        ))}
      </div>
      {dados && !dados.vazio && (
        <a
          href={urlExportCSV('ativos', janela)}
          download
          title="Exportar por ativo e mês (CSV para Excel)"
          className="hairline flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[12px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <Download size={13} aria-hidden="true" />
          CSV
        </a>
      )}
    </div>
  )

  return (
    <Card titulo="De onde veio o resultado" acao={acao}>
      {erro && <p className="text-[13px] text-critical">Não consegui calcular a composição: {erro}</p>}
      {!erro && !dados && <div className="shimmer h-48 rounded-lg" />}
      {dados?.vazio && (
        <p className="text-[13px] text-ink-3">Ainda não há extratos para separar o resultado por classe e ativo.</p>
      )}
      {dados && !dados.vazio && (
        <div className="space-y-5">
          <p className="text-[12px] text-ink-3">
            {periodo(dados.meses ?? [])}
            {(dados.janela.lacunas ?? []).length > 0 &&
              ` (sem extrato em ${dados.janela.lacunas!.map(fmtMes).join(', ')})`}
            {' · '}resultado = valorização + renda, descontadas compras e vendas.
          </p>

          {(dados.pendencias ?? []).length > 0 && (
            <Pendencias pendencias={dados.pendencias!} onResolver={(p, t) => void resolver(p, t)} />
          )}

          <TabelaClasses classes={dados.classes ?? []} caixa={dados.caixa ?? null} />

          <div>
            <p className="mb-1 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">Por ativo</p>
            <TabelaAtivos ativos={dados.ativos ?? []} janela={janela} />
          </div>

          <Notas dados={dados} />
        </div>
      )}
    </Card>
  )
}

/** Os meses com extrato na janela: "jul/26" ou "jan/26 a jul/26". */
function periodo(meses: string[]): string {
  if (meses.length === 0) return ''
  const [primeiro, ultimo] = [meses[0], meses[meses.length - 1]]
  return primeiro === ultimo ? fmtMes(primeiro) : `${fmtMes(primeiro)} a ${fmtMes(ultimo)}`
}

function opcoes(p: PendenciaAtivo): { tipo: string; rotulo: string }[] {
  const subiu = p.quantidade_fim > p.quantidade_ini
  const titulo = p.chave.startsWith('TD:') || p.chave.startsWith('RF:')
  const out: { tipo: string; rotulo: string }[] = []
  if (!titulo && p.quantidade_ini > 0 && p.quantidade_fim > 0) {
    out.push({
      tipo: 'EVENTO_SOCIETARIO',
      rotulo: subiu ? 'Desdobramento ou bonificação' : 'Grupamento',
    })
  }
  out.push(
    subiu
      ? { tipo: 'APORTE_EM_ATIVOS', rotulo: 'Veio de outra corretora' }
      : { tipo: 'RESGATE_EM_ATIVOS', rotulo: 'Foi para outra corretora' },
  )
  return out
}

function Pendencias({
  pendencias,
  onResolver,
}: {
  pendencias: PendenciaAtivo[]
  onResolver(p: PendenciaAtivo, tipo: string): void
}) {
  return (
    <div className="rounded-lg border border-serious/40 bg-serious/5 p-3">
      <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink">
        <CircleAlert size={14} className="shrink-0 text-serious" aria-hidden="true" />
        {pendencias.length === 1
          ? 'Um papel mudou de quantidade sem compra ou venda no extrato'
          : `${pendencias.length} papéis mudaram de quantidade sem compra ou venda no extrato`}
      </p>
      <ul className="mt-2 space-y-2">
        {pendencias.map((p) => (
          <li key={`${p.chave}-${p.mes}`} className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="min-w-0 flex-1 text-ink-2">
              <span className="font-medium text-ink">{p.ticker ?? p.nome ?? p.chave}</span> em{' '}
              {fmtMes(p.mes)}: de {fmtQtde(p.quantidade_ini)} para {fmtQtde(p.quantidade_fim)}. O que houve?
            </span>
            {opcoes(p).map((o) => (
              <button
                key={o.tipo}
                onClick={() => onResolver(p, o.tipo)}
                className="hairline rounded-md bg-surface px-2.5 py-1 text-[12px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
              >
                {o.rotulo}
              </button>
            ))}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-ink-3">
        Até a resposta, o resultado desses papéis fica de fora. O que veio ou foi para outra
        corretora conta como aporte ou resgate na rentabilidade da carteira.
      </p>
    </div>
  )
}

function Notas({ dados }: { dados: Composicao }) {
  const avisos = dados.avisos ?? []
  const c = dados.conciliacao
  const semAnterior = dados.janela.sem_mes_anterior ?? []
  const notas = avisos.filter((a) => NOTAS[a]).map((a) => NOTAS[a])
  if (semAnterior.length > 0) {
    notas.unshift(
      `Sem o extrato do mês anterior a ${semAnterior.map(fmtMes).join(', ')}: papéis que já existiam ficam sem número nesse mês.`,
    )
  }

  return (
    <div className="space-y-1.5 text-[11.5px] text-ink-3">
      {c && (
        <p className="flex items-start gap-1.5">
          {avisos.includes('residuo_alto') && (
            <TriangleAlert size={13} className="mt-px shrink-0 text-warn" aria-label="Atenção" />
          )}
          <span>
            Conferência ({c.meses_conferidos} {c.meses_conferidos === 1 ? 'mês' : 'meses'}): ganho da
            carteira {fmtBRLSinal(c.ganho_total)} = papéis {fmtBRLSinal(c.ativos)} + saldo e custos{' '}
            {fmtBRLSinal(c.rendimento_caixa + c.custos + c.outros)}
            {c.renda_sem_papel ? ` + renda sem papel ${fmtBRL(c.renda_sem_papel)}` : ''}
            {c.transito ? ` + valores em trânsito ${fmtBRLSinal(c.transito)}` : ''} + resíduo{' '}
            {fmtBRLSinal(c.residuo)}.
            {avisos.includes('residuo_alto') &&
              ' O resíduo é alto: algum fluxo não apareceu no extrato (compra de Tesouro sem o lote, por exemplo) ou o mês anterior não continua neste.'}
          </span>
        </p>
      )}
      {notas.map((n) => (
        <p key={n}>{n}</p>
      ))}
      <p>
        Rentabilidade do ativo pelo preço unitário (aportes não a distorcem); da classe, Modified
        Dietz. Sem a cotação diária, compra e venda no meio do mês são medidas pelo preço
        efetivo de cada uma.
      </p>
    </div>
  )
}
