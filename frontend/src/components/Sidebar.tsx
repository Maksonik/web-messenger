import { useEffect, useState } from 'react'
import { api } from '../api'
import type { ConnectionStatus } from '../realtime'
import type { Chat, User } from '../types'
import { chatAvatarSeed, chatTitle, formatShortDate, useDebounced } from '../utils'
import { Avatar } from './Avatar'

interface Props {
  me: User
  chats: Chat[]
  activeChatId: number | null
  unread: Record<number, number>
  status: ConnectionStatus
  onSelectChat: (chatId: number) => void
  onOpenDirect: (user: User) => void
  onNewGroup: () => void
  onLogout: () => void
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  online: 'в сети',
  connecting: 'подключение…',
  offline: 'нет соединения',
}

function preview(chat: Chat, meId: number): string {
  const last = chat.last_message
  if (!last) return chat.type === 'group' ? 'Группа создана' : 'Нет сообщений'
  const author =
    last.sender?.id === meId
      ? 'Вы: '
      : chat.type === 'group' && last.sender
        ? `${last.sender.display_name}: `
        : ''
  return author + last.text
}

export function Sidebar(props: Props) {
  const { me, chats, activeChatId, unread, status } = props
  const [query, setQuery] = useState('')
  const [people, setPeople] = useState<User[]>([])
  const debounced = useDebounced(query.trim())

  useEffect(() => {
    if (!debounced) return
    let cancelled = false
    api
      .searchUsers(debounced)
      .then((users) => !cancelled && setPeople(users))
      .catch(() => !cancelled && setPeople([]))
    return () => {
      cancelled = true
    }
  }, [debounced])

  const needle = query.trim().toLowerCase()
  const visibleChats = needle
    ? chats.filter((chat) => chatTitle(chat, me.id).toLowerCase().includes(needle))
    : chats

  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <Avatar name={me.display_name} seed={me.id} size={36} />
        <div className="grow">
          <div className="me-name">{me.display_name}</div>
          <div className={`status status-${status}`}>{STATUS_LABEL[status]}</div>
        </div>
        <button className="icon-button" onClick={props.onNewGroup} title="Новая группа">
          ＋
        </button>
        <button className="small" onClick={props.onLogout}>
          Выйти
        </button>
      </header>

      <div className="sidebar-search">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск чатов и людей"
        />
      </div>

      <nav className="chat-list">
        {visibleChats.map((chat) => {
          const title = chatTitle(chat, me.id)
          const count = unread[chat.id] ?? 0
          return (
            <button
              key={chat.id}
              className={`chat-item${chat.id === activeChatId ? ' active' : ''}`}
              onClick={() => props.onSelectChat(chat.id)}
            >
              <Avatar name={title} seed={chatAvatarSeed(chat, me.id)} />
              <div className="chat-item-body">
                <div className="chat-item-top">
                  <span className="chat-item-title">
                    {chat.type === 'group' && <span className="group-mark">👥 </span>}
                    {title}
                  </span>
                  {chat.last_message && (
                    <time className="muted">{formatShortDate(chat.last_message.created_at)}</time>
                  )}
                </div>
                <div className="chat-item-bottom">
                  <span className="chat-item-preview">{preview(chat, me.id)}</span>
                  {count > 0 && <span className="unread">{count}</span>}
                </div>
              </div>
            </button>
          )
        })}
        {!needle && chats.length === 0 && (
          <p className="empty-hint">
            Чатов пока нет. Найдите собеседника через поиск или создайте группу.
          </p>
        )}

        {debounced && (
          <>
            <div className="section-title">Люди</div>
            {people.length === 0 && <p className="empty-hint">Никого не нашли</p>}
            {people.map((user) => (
              <button
                key={user.id}
                className="chat-item"
                onClick={() => {
                  props.onOpenDirect(user)
                  setQuery('')
                }}
              >
                <Avatar name={user.display_name} seed={user.id} />
                <div className="chat-item-body">
                  <div className="chat-item-title">{user.display_name}</div>
                  <div className="muted">@{user.username}</div>
                </div>
              </button>
            ))}
          </>
        )}
      </nav>
    </aside>
  )
}
