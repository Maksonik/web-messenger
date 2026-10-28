import { useLayoutEffect, useRef, useState } from 'react'
import { ApiError } from '../api'
import type { ChatHistory } from '../messagesState'
import type { Attachment, Chat, Message, PendingMessage, User } from '../types'
import { chatAvatarSeed, chatPeer, chatTitle, formatTime, pluralMembers } from '../utils'
import { Avatar } from './Avatar'
import { Composer } from './Composer'
import { AttachmentList, MessageBubble, MessageText, ReplyQuote } from './MessageBubble'
import { MessageSearch } from './MessageSearch'

interface Props {
  chat: Chat
  me: User
  history: ChatHistory | undefined
  pending: PendingMessage[]
  onSend: (text: string, attachments: Attachment[], replyTo: Message | null) => void
  onRetry: (clientMsgId: string) => void
  onLoadMore: () => void
  onEdit: (message: Message, text: string) => Promise<unknown>
  onDelete: (message: Message) => Promise<unknown>
  onReact: (message: Message, emoji: string, on: boolean) => Promise<unknown>
  onToggleMute: () => Promise<unknown>
  onOpenMembers: () => void
  onBack: () => void
}

/** Distance from the bottom (px) within which new messages keep the view pinned. */
const STICK_THRESHOLD = 80

export function ChatView(props: Props) {
  const { chat, me, history, pending } = props
  const [draft, setDraft] = useState('')
  const [replyTo, setReplyTo] = useState<Message | null>(null)
  const [editing, setEditing] = useState<Message | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  // Scroll position saved before loading older messages, restored after they render.
  const anchor = useRef<{ height: number; top: number } | null>(null)
  // The unsent draft, kept aside while editing another message.
  const savedDraft = useRef('')

  const items = history?.items ?? []
  const title = chatTitle(chat, me.id)
  const subtitle =
    chat.type === 'group'
      ? pluralMembers(chat.members.length)
      : `@${chatPeer(chat, me.id)?.username ?? ''}`
  const isAdmin =
    chat.type === 'group' && chat.members.some((m) => m.user.id === me.id && m.role === 'admin')

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

  function jumpTo(messageId: number) {
    const element = listRef.current?.querySelector(`[data-message-id="${messageId}"]`)
    if (!element) {
      setNotice('Сообщение выше по истории — нажмите «Загрузить ещё»')
      return
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('flash')
    window.setTimeout(() => element.classList.remove('flash'), 1200)
  }

  async function run(action: () => Promise<unknown>) {
    try {
      await action()
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : 'Нет связи с сервером')
    }
  }

  function startEdit(message: Message) {
    if (!editing) savedDraft.current = draft
    setReplyTo(null)
    setEditing(message)
    setDraft(message.text)
  }

  function stopEdit() {
    setEditing(null)
    setDraft(savedDraft.current)
    savedDraft.current = ''
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
          className="icon-button"
          onClick={() => run(props.onToggleMute)}
          title={chat.muted ? 'Включить уведомления' : 'Выключить уведомления'}
        >
          {chat.muted ? '🔕' : '🔔'}
        </button>
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
        <div
          className="messages"
          ref={listRef}
          onScroll={onScroll}
          // Images grow the list after they load; stay pinned to the bottom if we were there.
          onLoadCapture={() => {
            const list = listRef.current
            if (list && stickToBottom.current) list.scrollTop = list.scrollHeight
          }}
        >
          <div className="messages-column">
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
                meId={me.id}
                members={chat.members}
                showAuthor={
                  // A deleted placeholder has no author line, so it doesn't continue a run.
                  chat.type === 'group' &&
                  (items[index - 1]?.sender?.id !== message.sender?.id ||
                    !!items[index - 1]?.deleted)
                }
                canDelete={message.sender?.id === me.id || isAdmin}
                onReply={() => {
                  if (editing) stopEdit()
                  setReplyTo(message)
                }}
                onEdit={() => startEdit(message)}
                onDelete={() => {
                  if (window.confirm('Удалить сообщение?')) void run(() => props.onDelete(message))
                }}
                onToggleReaction={(emoji, on) => run(() => props.onReact(message, emoji, on))}
                onJumpTo={jumpTo}
              />
            ))}
            {pending.map((p) => (
              <div key={p.clientMsgId} className="bubble mine pending">
                {p.replyTo && (
                  <ReplyQuote reply={p.replyTo} onClick={() => jumpTo(p.replyTo!.id)} />
                )}
                <AttachmentList attachments={p.attachments} />
                {p.text && (
                  <div className="bubble-text">
                    <MessageText text={p.text} members={chat.members} />
                  </div>
                )}
                <div className="bubble-meta">
                  {p.status === 'failed' ? (
                    <button
                      className="retry"
                      onClick={() => props.onRetry(p.clientMsgId)}
                      title={p.error}
                    >
                      ⚠ {p.error ?? 'не отправлено'} — повторить
                    </button>
                  ) : (
                    <span title="Отправляется">{formatTime(p.createdAt)} 🕓</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {searchOpen && <MessageSearch chatId={chat.id} onClose={() => setSearchOpen(false)} />}
      </div>

      {notice && (
        <div className="notice" role="status">
          <span className="grow">{notice}</span>
          <button className="icon-button" onClick={() => setNotice(null)} aria-label="Закрыть">
            ✕
          </button>
        </div>
      )}

      <Composer
        chatId={chat.id}
        meId={me.id}
        members={chat.members}
        replyTo={replyTo}
        editing={editing}
        draft={draft}
        onDraftChange={setDraft}
        onCancelReply={() => setReplyTo(null)}
        onCancelEdit={stopEdit}
        onSend={(text, attachments) => {
          stickToBottom.current = true
          props.onSend(text, attachments, replyTo)
          setReplyTo(null)
          setDraft('')
        }}
        onSaveEdit={(text) => {
          const message = editing!
          stopEdit()
          void run(() => props.onEdit(message, text))
        }}
      />
    </section>
  )
}
