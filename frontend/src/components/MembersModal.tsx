import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import type { Chat, User } from '../types'
import { pluralMembers } from '../utils'
import { Avatar } from './Avatar'
import { Modal } from './Modal'
import { UserPicker } from './UserPicker'

interface Props {
  chat: Chat
  me: User
  onClose: () => void
  /** Called after any change so the chat list is refreshed immediately. */
  onChanged: () => void
  onLeft: () => void
}

export function MembersModal({ chat, me, onClose, onChanged, onLeft }: Props) {
  const [title, setTitle] = useState(chat.title ?? '')
  const [error, setError] = useState<string | null>(null)
  const isAdmin = chat.members.some((m) => m.user.id === me.id && m.role === 'admin')

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Нет связи с сервером')
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault()
    void run(() => api.renameChat(chat.id, title.trim()))
  }

  async function leave() {
    if (!window.confirm('Покинуть группу?')) return
    setError(null)
    try {
      await api.removeMember(chat.id, me.id)
      onLeft()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Нет связи с сервером')
    }
  }

  return (
    <Modal title={chat.title ?? 'Группа'} onClose={onClose}>
      <div className="stack">
        {isAdmin && (
          <form className="inline-form" onSubmit={rename}>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
            <button type="submit" disabled={!title.trim() || title.trim() === chat.title}>
              Переименовать
            </button>
          </form>
        )}

        <div className="field-label">{pluralMembers(chat.members.length)}</div>
        <ul className="member-list">
          {chat.members.map(({ user, role }) => (
            <li key={user.id} className="user-row">
              <Avatar name={user.display_name} seed={user.id} size={32} />
              <span className="grow">
                <strong>{user.display_name}</strong>
                {user.id === me.id && <span className="muted"> (вы)</span>}
                <span className="muted"> @{user.username}</span>
              </span>
              {role === 'admin' && <span className="badge">админ</span>}
              {isAdmin && user.id !== me.id && (
                <button
                  className="danger small"
                  onClick={() => run(() => api.removeMember(chat.id, user.id))}
                >
                  Удалить
                </button>
              )}
            </li>
          ))}
        </ul>

        {isAdmin && (
          <div>
            <div className="field-label">Добавить участника</div>
            <UserPicker
              excludeIds={chat.members.map((m) => m.user.id)}
              onPick={(user) => run(() => api.addMember(chat.id, user.id))}
            />
          </div>
        )}

        {error && <p className="form-error">{error}</p>}
        <button className="danger" onClick={leave}>
          Покинуть группу
        </button>
      </div>
    </Modal>
  )
}
