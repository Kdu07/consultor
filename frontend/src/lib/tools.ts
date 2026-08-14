/** Nome da tool → o que mostrar no chip de status enquanto ela roda. */
const ROTULOS: Record<string, string> = {
  ler_carteira: 'lendo sua carteira',
  dados_ativo: 'consultando cotações',
  contexto_macro: 'checando o cenário macro',
  calcular_desvio: 'calculando desvios',
  importar_extrato: 'lendo o extrato',
  gravar_posicoes: 'gravando posições',
  noticias: 'buscando notícias',
  sugerir_rebalanceamento: 'analisando rebalanceamento',
  atualizar_estrategia: 'atualizando a estratégia',
  proposta_rebalanceamento: 'montando a proposta',
}

export function rotuloTool(nome: string): string {
  return ROTULOS[nome] ?? nome.replace(/_/g, ' ')
}

/** "lendo sua carteira e consultando cotações" */
export function frasearTools(nomes: string[]): string {
  const rotulos = [...new Set(nomes.map(rotuloTool))]
  if (rotulos.length === 0) return 'pensando'
  if (rotulos.length === 1) return rotulos[0]
  return `${rotulos.slice(0, -1).join(', ')} e ${rotulos[rotulos.length - 1]}`
}
