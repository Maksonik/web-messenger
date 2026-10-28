import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import type { User } from '../types'

interface Props {
  onAuthenticated: (user: User) => void
}

function describeError(error: unknown, mode: 'login' | 'register'): string {
  if (!(error instanceof ApiError)) return 'Нет связи с сервером. Попробуйте ещё раз.'
  if (mode === 'login' && error.status === 401) return 'Неверный логин или пароль'
  if (error.status === 409) return 'Этот логин уже занят'
  if (error.status === 422) {
    return 'Логин: 3–32 символа (латиница, цифры, _). Пароль: не короче 8 символов.'
  }
  return error.message
}

export function LoginPage({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const auth =
        mode === 'login'
          ? await api.login(username, password)
          : await api.register(username, password, displayName.trim())
      onAuthenticated(auth.user)
    } catch (err) {
      setError(describeError(err, mode))
    } finally {
      setBusy(false)
    }
  }

  const isLogin = mode === 'login'
  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <img src="/favicon.svg" alt="" width={56} height={56} />
        <h1>{isLogin ? 'Вход в мессенджер' : 'Регистрация'}</h1>

        <label>
          Логин
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>
        {!isLogin && (
          <label>
            Имя <span className="muted">(необязательно)</span>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
              maxLength={64}
            />
          </label>
        )}
        <label>
          Пароль
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={isLogin ? 'current-password' : 'new-password'}
            required
          />
        </label>

        {error && <p className="form-error">{error}</p>}

        <button className="primary" type="submit" disabled={busy}>
          {isLogin ? 'Войти' : 'Зарегистрироваться'}
        </button>
        <button
          type="button"
          className="link"
          onClick={() => {
            setMode(isLogin ? 'register' : 'login')
            setError(null)
          }}
        >
          {isLogin ? 'Нет аккаунта? Зарегистрироваться' : 'Уже есть аккаунт? Войти'}
        </button>
      </form>
    </main>
  )
}
