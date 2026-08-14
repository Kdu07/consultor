import { useEffect, useRef, useState } from 'react'
import { Lock, TriangleAlert } from 'lucide-react'
import { fazerLogin } from '../lib/api'

interface Props {
  /** Chamado quando a senha é aceita — o App volta a montar a aplicação. */
  onEntrou(): void
}

export default function Login({ onEntrou }: Props) {
  const [senha, setSenha] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => inputRef.current?.focus(), [])

  async function entrar(e: React.FormEvent) {
    e.preventDefault()
    if (!senha || enviando) return
    setEnviando(true)
    setErro(null)
    try {
      await fazerLogin(senha)
      setSenha('')
      onEntrou()
    } catch (err) {
      setErro((err as Error).message || 'Não consegui entrar.')
      setEnviando(false)
      inputRef.current?.select()
    }
  }

  return (
    <div className="flex h-dvh items-center justify-center bg-plane p-4">
      <form
        onSubmit={entrar}
        className="hairline fade-up w-full max-w-[380px] rounded-2xl bg-surface p-6 shadow-[0_24px_64px_rgba(0,0,0,0.6)]"
      >
        <div className="mb-1 flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <Lock size={15} />
          </span>
          <h1 className="text-[16px] font-semibold">Consultor</h1>
        </div>

        <p className="mb-5 text-[13px] leading-relaxed text-ink-2">
          Esta carteira é privada. Informe a senha de acesso para continuar.
        </p>

        <label htmlFor="senha" className="mb-1.5 block text-[12.5px] text-ink-3">
          Senha
        </label>
        <input
          id="senha"
          ref={inputRef}
          type="password"
          autoComplete="current-password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          disabled={enviando}
          className="hairline w-full rounded-lg bg-surface-2 px-3 py-2.5 text-[14px] text-ink outline-none placeholder:text-ink-3 focus:border-accent disabled:opacity-60"
          placeholder="••••••••"
        />

        {erro && (
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-surface-2 p-2.5 text-[13px] text-critical">
            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
            <span>{erro}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={!senha || enviando}
          className="mt-4 w-full rounded-lg bg-accent px-4 py-2.5 text-[13px] font-medium text-white transition-all enabled:hover:brightness-110 disabled:bg-surface-3 disabled:text-ink-3"
        >
          {enviando ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
