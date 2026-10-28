import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import type { ChatHistory } from '../messagesState'
import type { Chat, Message, PendingMessage, User } from '../types'
import { chatAvatarSeed, chatPeer, chatTitle, formatTime, pluralMembers } from '../utils'
import { Avatar } from './Avatar'
import { MessageSearch } from './MessageSearch'

interface Props {
  chat: Chat
  me: User
  history: ChatHistory | undefined
  pending: PendingMessage[]
  onSend: (text: string) => void
  onRetry: (clientMsgId: string) => void
  onLoadMore: () => void
  onOpenMembers: () => void
  onBack: () => void
}

/** Distance from the bottom (px) within which new messages keep the view pinned. */
const STICK_THRESHOLD = 80

export function ChatView(props: Props) {
  const { chat, me, history, pending } = props
  const [draft, setDraft] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  // Scroll position saved before loading older messages, restored after they render.
  const anchor = useRef<{ height: number; top: number } | null>(null)

  const items = history?.items ?? []
  const title = chatTitle(chat, me.id)
  const subtitle =
    chat.type === 'group'
      ? pluralMembers(chat.members.length)
      : `@${chatPeer(chat, me.id)?.username ?? ''}`

  useLayoutEffect(() => {
    const list = listRef.current
    if (!list) return
    if (anchor.current) {
      list.scrollTop = list.scrollHeight - anchor.current.height + anchor.current.top
      anchor.current = null
    } else if (stickToBottom.current) {
      list.scrollTop = list.scrollHeight
    }
  }, [items.length, pending.length])

  function onScroll() {
    const list = listRef.current
    if (!list) return
    stickToBottom.current = list.scrollHeight - list.scrollTop - list.clientHeight < STICK_THRESHOLD
  }

  function loadMore() {
    const list = listRef.current
    if (list) anchor.current = { height: list.scrollHeight, top: list.scrollTop }
    props.onLoadMore()
  }

  function submit(event?: FormEvent) {
    event?.preventDefault()
    const text = draft.trim()
    if (!text) return
    stickToBottom.current = true
    props.onSend(text)
    setDraft('')
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <section className="chat-view">
      <header className="chat-header">
        <button className="icon-button back-button" onClick={props.onBack} aria-label="Назад">
          ←
        </button>
        <Avatar name={title} seed={chatAvatarSeed(chat, me.id)} size={38} />
        <div className="grow">
          <div className="chat-title">{title}</div>
          <div className="muted">{subtitle}</div>
        </div>
        <button
          className={`icon-button${searchOpen ? ' active' : ''}`}
          onClick={() => setSearchOpen((open) => !open)}
          title="Поиск по сообщениям"
        >
          🔍
        </button>
        {chat.type === 'group' && (
          <button className="icon-button" onClick={props.onOpenMembers} title="Участники">
            👥
          </button>
        )}
      </header>

      <div className="chat-body">
        <div className="messages" ref={listRef} onScroll={onScroll}>
          {history?.hasMore && (
            <button className="load-more" onClick={loadMore} disabled={history.loadingMore}>
              {history.loadingMore ? 'Загрузка…' : 'Загрузить ещё'}
            </button>
          )}
          {!history && <p className="empty-hint">Загрузка…</p>}
          {history && items.length === 0 && pending.length === 0 && (
            <p className="empty-hint">Сообщений пока нет. Напишите первым!</p>
          )}

          {items.map((message, index) => (
            <MessageBubble
              key={message.id}
              message={message}
              mine={message.sender?.id === me.id}
              showAuthor={
                chat.type === 'group' && items[index - 1]?.sender?.id !== message.sender?.id
              }
            />
          ))}
          {pending.map((p) => (
            <div key={p.clientMsgId} className="bubble mine pending">
              <div className="bubble-text">{p.text}</div>
              <div className="bubble-meta">
                {p.status === 'failed' ? (
                  <button
                    className="retry"
                    onClick={() => props.onRetry(p.clientMsgId)}
                    title={p.error}
                  >
                    ⚠ не отправлено — повторить
                  </button>
                ) : (
                  <span title="Отправляется">{formatTime(p.createdAt)} 🕓</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {searchOpen && <MessageSearch chatId={chat.id} onClose={() => setSearchOpen(false)} />}
      </div>

      <form className="composer" onSubmit={submit}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Сообщение"
          rows={1}
          maxLength={4000}
          autoFocus
        />
        <button className="primary" type="submit" disabled={!draft.trim()}>
          Отправить
        </button>
      </form>
    </section>
  )
}

function MessageBubble({
  message,
  mine,
  showAuthor,
}: {
  message: Message
  mine: boolean
  showAuthor: boolean
}) {
  return (
    <div className={`bubble${mine ? ' mine' : ''}`}>
      {showAuthor && !mine && (
        <div className="bubble-author">
          {message.sender?.display_name ?? 'Удалённый пользователь'}
        </div>
      )}
      <div className="bubble-text">{message.text}</div>
      <div className="bubble-meta">
        {formatTime(message.created_at)}
        {/* "Delivered to the server": the message has a server id. */}
        {mine && <span title="Доставлено на сервер"> ✓</span>}
      </div>
    </div>
  )
}
