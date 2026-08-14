export default function Card({
  titulo,
  acao,
  children,
}: {
  titulo?: string
  acao?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="hairline rounded-xl bg-surface p-4">
      {(titulo || acao) && (
        <header className="mb-3 flex items-center gap-2">
          {titulo && (
            <h2 className="flex-1 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
              {titulo}
            </h2>
          )}
          {acao}
        </header>
      )}
      {children}
    </section>
  )
}
