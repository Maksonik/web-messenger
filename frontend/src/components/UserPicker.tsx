import { useEffect, useState } from 'react'
import { api } from '../api'
import type { User } from '../types'
import { useDebounced } from '../utils'
import { Avatar } from './Avatar'

interface Props {
  onPick: (user: User) => void
  excludeIds?: number[]
  placeholder?: string
}

/** Search box with a dropdown of matching users. */
export function UserPicker({ onPick, excludeIds = [], placeholder = 'Найти пользователя' }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<User[]>([])
  const debounced = useDebounced(query.trim())

  useEffect(() => {
    if (!debounced) return
    let cancelled = false
    api
      .searchUsers(debounced)
      .then((users) => !cancelled && setResults(users))
      .catch(() => !cancelled && setResults([]))
    return () => {
      cancelled = true
    }
  }, [debounced])

  const visible = debounced ? results.filter((u) => !excludeIds.includes(u.id)) : []

  return (
    <div className="user-picker">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
      />
      {debounced && (
        <ul className="user-picker-results">
          {visible.length === 0 && <li className="muted">Никого не нашли</li>}
          {visible.map((user) => (
            <li key={user.id}>
              <button
                type="button"
                className="user-row"
                onClick={() => {
                  onPick(user)
                  setQuery('')
                }}
              >
                <Avatar name={user.display_name} seed={user.id} size={32} />
                <span>
                  <strong>{user.display_name}</strong>
                  <span className="muted"> @{user.username}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
