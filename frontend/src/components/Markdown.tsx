import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Markdown da resposta do agente. Tabelas ganham scroll próprio para que o
 * corpo da página nunca role na horizontal, e números em coluna usam figuras
 * tabulares para alinhar.
 */
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="text-[15px] leading-[1.65] text-ink">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: (p) => <p className="mb-3 last:mb-0" {...p} />,
          strong: (p) => <strong className="font-semibold text-ink" {...p} />,
          em: (p) => <em className="italic text-ink-2" {...p} />,
          ul: (p) => (
            <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0" {...p} />
          ),
          ol: (p) => (
            <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0" {...p} />
          ),
          li: (p) => <li className="pl-0.5 marker:text-ink-3" {...p} />,
          h1: (p) => (
            <h1 className="mt-5 mb-2 text-lg font-semibold first:mt-0" {...p} />
          ),
          h2: (p) => (
            <h2
              className="mt-5 mb-2 text-base font-semibold first:mt-0"
              {...p}
            />
          ),
          h3: (p) => (
            <h3
              className="mt-4 mb-1.5 text-[15px] font-semibold first:mt-0"
              {...p}
            />
          ),
          blockquote: (p) => (
            <blockquote
              className="my-3 border-l-2 border-surface-3 pl-3 text-ink-2"
              {...p}
            />
          ),
          hr: () => <hr className="my-4 border-0 border-t border-line" />,
          a: (p) => (
            <a
              className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
              target="_blank"
              rel="noreferrer"
              {...p}
            />
          ),
          code: ({ className, children, ...rest }) => {
            const emBloco = /language-/.test(className ?? '')
            if (emBloco) {
              return (
                <code
                  className="block font-mono text-[13px] leading-relaxed"
                  {...rest}
                >
                  {children}
                </code>
              )
            }
            return (
              <code
                className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[13px] text-ink-2"
                {...rest}
              >
                {children}
              </code>
            )
          },
          pre: (p) => (
            <pre
              className="mb-3 overflow-x-auto rounded-lg bg-surface-2 p-3 last:mb-0"
              {...p}
            />
          ),
          table: (p) => (
            <div className="mb-3 overflow-x-auto last:mb-0">
              <table
                className="w-full border-collapse text-[13px] tabular-nums"
                {...p}
              />
            </div>
          ),
          thead: (p) => <thead className="text-ink-3" {...p} />,
          th: (p) => (
            <th
              className="hairline-b px-2.5 py-1.5 text-left text-[11px] font-semibold tracking-wide uppercase whitespace-nowrap"
              {...p}
            />
          ),
          td: (p) => (
            <td className="border-t border-line px-2.5 py-1.5" {...p} />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
