import type { Classe } from './api'

/**
 * Ordem fixa das classes. É por ela que qualquer barra empilhada é desenhada —
 * nunca por valor. Ordenar por grandeza trocaria os pares adjacentes de cor e
 * derrubaria a validação CVD da paleta (ver comentário no index.css).
 */
export const ORDEM_CLASSES: Classe[] = [
  'ACAO',
  'FII',
  'ETF',
  'BDR',
  'TESOURO',
  'RF',
  'FUNDO',
  'CAIXA',
  // CRIPTO entra no FIM: preserva todos os pares adjacentes já validados e cria
  // um único par novo (CAIXA–CRIPTO, vermelho × teal — separação CVD folgada).
  'CRIPTO',
]

/** Slot categórico de cada classe — a cor segue a entidade, jamais o ranking. */
const COR: Record<Classe, string> = {
  ACAO: 'var(--color-s1)',
  FII: 'var(--color-s2)',
  ETF: 'var(--color-s3)',
  BDR: 'var(--color-s4)',
  TESOURO: 'var(--color-s5)',
  RF: 'var(--color-s6)',
  FUNDO: 'var(--color-s7)',
  CAIXA: 'var(--color-s8)',
  // Slot 9 (teal). O fallback literal vale até o index.css ganhar --color-s9;
  // quando o token existir, o var() passa a mandar sem mexer aqui.
  CRIPTO: 'var(--color-s9, #1ba2a6)',
}

const ROTULO: Record<Classe, string> = {
  ACAO: 'Ações',
  FII: 'FIIs',
  ETF: 'ETFs',
  BDR: 'BDRs',
  TESOURO: 'Tesouro',
  RF: 'Renda fixa',
  FUNDO: 'Fundos',
  CAIXA: 'Caixa',
  CRIPTO: 'Cripto',
}

export function corDaClasse(c: string): string {
  return COR[c as Classe] ?? 'var(--color-ink-3)'
}

export function rotuloDaClasse(c: string): string {
  return ROTULO[c as Classe] ?? c
}

export function ordemDaClasse(c: string): number {
  const i = ORDEM_CLASSES.indexOf(c as Classe)
  return i === -1 ? 99 : i
}
