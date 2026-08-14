import {
  ChartPie,
  Newspaper,
  Scale,
  Sparkles,
  Upload,
  type LucideIcon,
} from 'lucide-react'

interface Atalho {
  icone: LucideIcon
  titulo: string
  descricao: string
  /** Texto enviado ao agente; `null` abre o modal de import. */
  prompt: string | null
}

const ATALHOS: Atalho[] = [
  {
    icone: ChartPie,
    titulo: 'Como está minha carteira?',
    descricao: 'Panorama com valores ao vivo',
    prompt: 'Como está minha carteira hoje?',
  },
  {
    icone: Scale,
    titulo: 'Saí do meu alvo?',
    descricao: 'Desvios por classe e ativo',
    prompt: 'Minha carteira saiu do alvo? Onde estão os maiores desvios?',
  },
  {
    icone: Newspaper,
    titulo: 'Notícias dos meus ativos',
    descricao: 'O que saiu sobre a carteira',
    prompt: 'Traga as notícias relevantes sobre os ativos da minha carteira.',
  },
  {
    icone: Upload,
    titulo: 'Importar extrato BTG',
    descricao: 'Envie o XLSX do mês',
    prompt: null,
  },
]

function saudacao(): string {
  const h = new Date().getHours()
  if (h < 5) return 'Boa madrugada'
  if (h < 12) return 'Bom dia'
  if (h < 18) return 'Boa tarde'
  return 'Boa noite'
}

interface Props {
  onPrompt(texto: string): void
  onImportar(): void
}

export default function EstadoVazio({ onPrompt, onImportar }: Props) {
  return (
    <div className="fade-up flex h-full flex-col items-center justify-center px-4 py-10">
      <div className="mb-4 flex size-11 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        <Sparkles size={20} />
      </div>

      <h1 className="text-2xl font-semibold tracking-tight">{saudacao()}</h1>
      <p className="mt-1.5 mb-8 text-[15px] text-ink-3">
        Sobre o que quer conversar hoje?
      </p>

      <div className="grid w-full max-w-[640px] grid-cols-1 gap-2.5 sm:grid-cols-2">
        {ATALHOS.map((a) => (
          <button
            key={a.titulo}
            onClick={() => (a.prompt ? onPrompt(a.prompt) : onImportar())}
            className="hairline group flex items-start gap-3 rounded-xl bg-surface p-3.5 text-left transition-colors hover:bg-surface-2"
          >
            <a.icone
              size={17}
              className="mt-0.5 shrink-0 text-ink-3 transition-colors group-hover:text-accent"
            />
            <span className="min-w-0">
              <span className="block text-[14px] font-medium text-ink">
                {a.titulo}
              </span>
              <span className="block text-[12px] text-ink-3">
                {a.descricao}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
