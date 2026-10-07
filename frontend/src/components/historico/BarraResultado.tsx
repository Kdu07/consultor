/**
 * Barra divergente de uma linha de tabela: sai do zero (o traço do meio) para a
 * direita quando o resultado é ganho e para a esquerda quando é perda. A cor é
 * a da classe — só identidade; o sinal está na direção e no número ao lado.
 * Ponta arredondada só na extremidade do dado, reta no zero.
 */
export default function BarraResultado({
  valor,
  maior,
  cor,
}: {
  valor: number | null
  /** Maior |resultado| da tabela: a mesma escala para todas as linhas. */
  maior: number
  cor: string
}) {
  const metade = valor == null || maior <= 0 ? 0 : Math.max(1.5, (Math.abs(valor) / maior) * 50)
  return (
    <span className="relative block h-2 w-full min-w-16 rounded-[2px] bg-surface-2" aria-hidden="true">
      <span className="absolute -inset-y-0.5 left-1/2 w-px bg-baseline" />
      {valor != null && valor !== 0 && (
        <span
          className="absolute inset-y-0"
          style={{
            backgroundColor: cor,
            width: `${metade}%`,
            left: valor > 0 ? '50%' : `${50 - metade}%`,
            borderRadius: valor > 0 ? '0 4px 4px 0' : '4px 0 0 4px',
          }}
        />
      )}
    </span>
  )
}
