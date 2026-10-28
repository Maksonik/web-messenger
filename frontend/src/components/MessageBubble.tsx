import { useState, type ReactNode } from 'react'
import { REACTIONS, type Attachment, type Member, type Message, type ReplyPreview } from '../types'
import { formatFileSize, formatTime } from '../utils'

interface Props {
  message: Message
  meId: number
  members: Member[]
  showAuthor: boolean
  canDelete: boolean
  onReply: () => void
  onEdit: () => void
  onDelete: () => void
  onToggleReaction: (emoji: string, on: boolean) => void
  onJumpTo: (messageId: number) => void
}

const MENTION_SPLIT = /(@[A-Za-z0-9_]{3,32})/g

/** Highlights @mentions of chat members; other text is rendered as is. */
export function MessageText({ text, members }: { text: string; members: Member[] }) {
  const usernames = new Set(members.map((m) => m.user.username))
  const parts: ReactNode[] = text.split(MENTION_SPLIT).map((part, i) =>
    i % 2 === 1 && usernames.has(part.slice(1).toLowerCase()) ? (
      <span key={i} className="mention">
        {part}
      </span>
    ) : (
      part
    ),
  )
  return <>{parts}</>
}

export function ReplyQuote({ reply, onClick }: { reply: ReplyPreview; onClick?: () => void }) {
  return (
    <button type="button" className="reply-quote" onClick={onClick} disabled={!onClick}>
      <strong>{reply.sender?.display_name ?? 'Удалённый пользователь'}</strong>
      <span>{reply.deleted ? 'Сообщение удалено' : reply.text || 'Вложение'}</span>
    </button>
  )
}

export function AttachmentList({ attachments }: { attachments: Attachment[] }) {
  if (attachments.length === 0) return null
  const images = attachments.filter((a) => a.is_image)
  const files = attachments.filter((a) => !a.is_image)
  return (
    <div className="attachments">
      {images.length > 0 && (
        <div className="attachment-images">
          {images.map((a) => (
            <a key={a.id} href={a.url} target="_blank" rel="noreferrer">
              <img src={a.url} alt={a.filename} loading="lazy" />
            </a>
          ))}
        </div>
      )}
      {files.map((a) => (
        <a key={a.id} className="attachment-file" href={a.url} download={a.filename}>
          <span className="attachment-icon">📄</span>
          <span className="grow">
            <span className="attachment-name">{a.filename}</span>
            <span className="muted">{formatFileSize(a.size)}</span>
          </span>
        </a>
      ))}
    </div>
  )
}

export function MessageBubble(props: Props) {
  const { message, meId, members } = props
  const [pickerOpen, setPickerOpen] = useState(false)
  const mine = message.sender?.id === meId
  const mentionsMe = message.mention_user_ids.includes(meId)

  if (message.deleted) {
    return (
      <div className={`bubble deleted${mine ? ' mine' : ''}`} data-message-id={message.id}>
        <span className="muted">🗑 Сообщение удалено</span>
      </div>
    )
  }

  // Read receipts: who else has read up to this message.
  const readers = members.filter(
    (m) => m.user.id !== meId && (m.last_read_message_id ?? 0) >= message.id,
  )

  return (
    <div
      className={`bubble${mine ? ' mine' : ''}${mentionsMe ? ' mentioned' : ''}`}
      data-message-id={message.id}
    >
      <div className="bubble-actions">
        <button title="Ответить" onClick={props.onReply}>
          ↩
        </button>
        <button title="Реакция" onClick={() => setPickerOpen((open) => !open)}>
          😊
        </button>
        {mine && (
          <button title="Редактировать" onClick={props.onEdit}>
            ✏️
          </button>
        )}
        {props.canDelete && (
          <button title="Удалить" onClick={props.onDelete}>
            🗑
          </button>
        )}
      </div>
      {pickerOpen && (
        <div className="reaction-picker" onMouseLeave={() => setPickerOpen(false)}>
          {REACTIONS.map((emoji) => {
            const on = message.reactions.some((r) => r.emoji === emoji && r.user_ids.includes(meId))
            return (
              <button
                key={emoji}
                className={on ? 'on' : ''}
                onClick={() => {
                  props.onToggleReaction(emoji, !on)
                  setPickerOpen(false)
                }}
              >
                {emoji}
              </button>
            )
          })}
        </div>
      )}

      {props.showAuthor && !mine && (
        <div className="bubble-author">
          {message.sender?.display_name ?? 'Удалённый пользователь'}
        </div>
      )}
      {message.reply_to && (
        <ReplyQuote reply={message.reply_to} onClick={() => props.onJumpTo(message.reply_to!.id)} />
      )}
      <AttachmentList attachments={message.attachments} />
      {message.text && (
        <div className="bubble-text">
          <MessageText text={message.text} members={members} />
        </div>
      )}

      {message.reactions.length > 0 && (
        <div className="reactions">
          {message.reactions.map((r) => {
            const on = r.user_ids.includes(meId)
            const names = members
              .filter((m) => r.user_ids.includes(m.user.id))
              .map((m) => m.user.display_name)
              .join(', ')
            return (
              <button
                key={r.emoji}
                className={`reaction${on ? ' on' : ''}`}
                title={names}
                onClick={() => props.onToggleReaction(r.emoji, !on)}
              >
                {r.emoji} {r.count}
              </button>
            )
          })}
        </div>
      )}

      <div className="bubble-meta">
        {message.edited_at && (
          <span title={`Изменено ${formatTime(message.edited_at)}`}>изм. </span>
        )}
        {formatTime(message.created_at)}
        {mine &&
          (readers.length > 0 ? (
            <span
              className="read-mark"
              title={`Прочитано: ${readers.map((m) => m.user.display_name).join(', ')}`}
            >
              {' '}
              ✓✓
            </span>
          ) : (
            <span title="Доставлено на сервер"> ✓</span>
          ))}
      </div>
    </div>
  )
}
