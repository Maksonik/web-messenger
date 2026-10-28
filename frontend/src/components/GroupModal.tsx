import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import type { Chat, User } from '../types'
import { Modal } from './Modal'
import { UserPicker } from './UserPicker'

interface Props {
  me: User
  onClose: () => void
  onCreated: (chat: Chat) => void
}

export function GroupModal({ me, onClose, onCreated }: Props) {
  const [title, setTitle] = useState('')
  const [members, setMembers] = useState<User[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(
        await api.createGroup(
          title.trim(),
          members.map((m) => m.id),
        ),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Нет связи с сервером')
      setBusy(false)
    }
  }

  return (
    <Modal title="Новая группа" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label>
          Название
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={100}
            autoFocus
            required
          />
        </label>

        <div>
          <div className="field-label">Участники</div>
          <UserPicker
            excludeIds={[me.id, ...members.map((m) => m.id)]}
            onPick={(user) => setMembers((prev) => [...prev, user])}
          />
          {members.length > 0 && (
            <ul className="chips">
              {members.map((user) => (
                <li key={user.id} className="chip">
                  {user.display_name}
                  <button
                    type="button"
                    aria-label={`Убрать ${user.display_name}`}
                    onClick={() => setMembers((prev) => prev.filter((m) => m.id !== user.id))}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && <p className="form-error">{error}</p>}
        <button className="primary" type="submit" disabled={busy || !title.trim()}>
          Создать группу
        </button>
      </form>
    </Modal>
  )
}
