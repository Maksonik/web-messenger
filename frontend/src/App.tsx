import { useCallback, useEffect, useState } from 'react'
import { api, refreshSession, setUnauthorizedHandler } from './api'
import { LoginPage } from './components/LoginPage'
import { Messenger } from './components/Messenger'
import type { User } from './types'

type Session =
  | { status: 'loading' }
  | { status: 'offline' }
  | { status: 'anonymous' }
  | { status: 'authenticated'; user: User }

/** Restores the session from the refresh cookie. */
function loadSession(): Promise<Session> {
  return refreshSession().then(
    (auth) => (auth ? { status: 'authenticated', user: auth.user } : { status: 'anonymous' }),
    () => ({ status: 'offline' }),
  )
}

export default function App() {
  const [session, setSession] = useState<Session>({ status: 'loading' })

  const expire = useCallback(() => setSession({ status: 'anonymous' }), [])

  useEffect(() => {
    setUnauthorizedHandler(expire)
    void loadSession().then(setSession)
  }, [expire])

  async function logout() {
    try {
      await api.logout()
    } finally {
      setSession({ status: 'anonymous' })
    }
  }

  switch (session.status) {
    case 'loading':
      return <div className="splash">Загрузка…</div>
    case 'offline':
      return (
        <div className="splash">
          <p>Нет связи с сервером</p>
          <button
            className="primary"
            onClick={() => {
              setSession({ status: 'loading' })
              void loadSession().then(setSession)
            }}
          >
            Повторить
          </button>
        </div>
      )
    case 'anonymous':
      return <LoginPage onAuthenticated={(user) => setSession({ status: 'authenticated', user })} />
    case 'authenticated':
      return <Messenger me={session.user} onLogout={logout} onSessionExpired={expire} />
  }
}
