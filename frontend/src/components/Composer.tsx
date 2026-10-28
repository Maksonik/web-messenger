import { useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from 'react'
import { api, ApiError } from '../api'
import type { Attachment, Member, Message } from '../types'
import { formatFileSize, messageSummary } from '../utils'

const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_ATTACHMENTS = 10
/** "@que" right before the caret. */
const MENTION_AT_CARET = /(^|\s)@([A-Za-z0-9_]{0,32})$/

interface Upload {
  localId: string
  name: string
  size: number
  status: 'uploading' | 'done' | 'error'
  attachment?: Attachment
  error?: string
}

interface Props {
  chatId: number
  meId: number
  members: Member[]
  replyTo: Message | null
  editing: Message | null
  draft: string
  onDraftChange: (draft: string) => void
  onCancelReply: () => void
  onCancelEdit: () => void
  onSend: (text: string, attachments: Attachment[]) => void
  onSaveEdit: (text: string) => void
}

export function Composer(props: Props) {
  const { draft, editing, replyTo } = props
  const [uploads, setUploads] = useState<Upload[]>([])
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const uploading = uploads.some((u) => u.status === 'uploading')
  const ready = uploads.filter((u) => u.status === 'done').map((u) => u.attachment!)
  const canSubmit = editing
    ? draft.trim().length > 0 || editing.attachments.length > 0
    : !uploading && (draft.trim().length > 0 || ready.length > 0)

  const suggestions =
    mentionQuery === null
      ? []
      : props.members
          .filter((m) => m.user.id !== props.meId)
          .filter(
            (m) =>
              m.user.username.startsWith(mentionQuery.toLowerCase()) ||
              m.user.display_name.toLowerCase().startsWith(mentionQuery.toLowerCase()),
          )
          .slice(0, 5)

  function addFiles(files: File[]) {
    const room = MAX_ATTACHMENTS - uploads.length
    for (const file of files.slice(0, Math.max(room, 0))) {
      const upload: Upload = {
        localId: crypto.getRandomValues(new Uint32Array(2)).join('-'),
        name: file.name || 'image.png',
        size: file.size,
        status: 'uploading',
      }
      if (file.size > MAX_FILE_BYTES) {
        setUploads((prev) => [...prev, { ...upload, status: 'error', error: 'больше 10 МБ' }])
        continue
      }
      setUploads((prev) => [...prev, upload])
      api
        .uploadAttachment(props.chatId, file)
        .then((attachment) =>
          setUploads((prev) =>
            prev.map((u) =>
              u.localId === upload.localId ? { ...u, status: 'done', attachment } : u,
            ),
          ),
        )
        .catch((err) =>
          setUploads((prev) =>
            prev.map((u) =>
              u.localId === upload.localId
                ? {
                    ...u,
                    status: 'error',
                    error: err instanceof ApiError ? err.message : 'нет связи',
                  }
                : u,
            ),
          ),
        )
    }
  }

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!canSubmit) return
    if (editing) {
      props.onSaveEdit(draft.trim())
    } else {
      props.onSend(draft.trim(), ready)
      setUploads([])
    }
    setMentionQuery(null)
  }

  function updateMentionQuery(text: string, caret: number) {
    const match = MENTION_AT_CARET.exec(text.slice(0, caret))
    setMentionQuery(match ? match[2] : null)
  }

  function insertMention(username: string) {
    const textarea = textareaRef.current
    const caret = textarea?.selectionStart ?? draft.length
    const before = draft.slice(0, caret).replace(/@([A-Za-z0-9_]{0,32})$/, `@${username} `)
    props.onDraftChange(before + draft.slice(caret))
    setMentionQuery(null)
    requestAnimationFrame(() => {
      textarea?.focus()
      textarea?.setSelectionRange(before.length, before.length)
    })
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (suggestions.length > 0 && (event.key === 'Tab' || event.key === 'Enter')) {
      event.preventDefault()
      insertMention(suggestions[0].user.username)
    } else if (event.key === 'Escape') {
      if (editing) props.onCancelEdit()
      else if (replyTo) props.onCancelReply()
      setMentionQuery(null)
    } else if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = [...event.clipboardData.files]
    if (files.length > 0 && !editing) {
      event.preventDefault()
      addFiles(files)
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-inner">
        {(replyTo || editing) && (
          <div className="composer-banner">
            <span className="composer-banner-icon">{editing ? '✏️' : '↩'}</span>
            <div className="grow">
              <strong>
                {editing
                  ? 'Редактирование'
                  : `Ответ: ${replyTo!.sender?.display_name ?? 'удалённый пользователь'}`}
              </strong>
              <div className="muted ellipsis">{messageSummary((editing ?? replyTo)!)}</div>
            </div>
            <button
              type="button"
              className="icon-button"
              aria-label="Отменить"
              onClick={editing ? props.onCancelEdit : props.onCancelReply}
            >
              ✕
            </button>
          </div>
        )}

        {uploads.length > 0 && (
          <ul className="uploads">
            {uploads.map((u) => (
              <li key={u.localId} className={`upload ${u.status}`}>
                <span className="ellipsis">{u.name}</span>
                <span className="muted">
                  {u.status === 'uploading'
                    ? 'загрузка…'
                    : u.status === 'error'
                      ? `ошибка: ${u.error}`
                      : formatFileSize(u.size)}
                </span>
                <button
                  type="button"
                  aria-label={`Убрать ${u.name}`}
                  onClick={() => setUploads((prev) => prev.filter((x) => x.localId !== u.localId))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}

        {suggestions.length > 0 && (
          <ul className="mention-suggestions">
            {suggestions.map((m) => (
              <li key={m.user.id}>
                <button type="button" onClick={() => insertMention(m.user.username)}>
                  <strong>{m.user.display_name}</strong>
                  <span className="muted"> @{m.user.username}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="composer-row">
          {!editing && (
            <>
              <button
                type="button"
                className="icon-button"
                title="Прикрепить файл"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploads.length >= MAX_ATTACHMENTS}
              >
                📎
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  addFiles([...(e.target.files ?? [])])
                  e.target.value = ''
                }}
              />
            </>
          )}
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => {
              props.onDraftChange(e.target.value)
              updateMentionQuery(e.target.value, e.target.selectionStart)
            }}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            placeholder="Сообщение"
            rows={1}
            maxLength={4000}
            autoFocus
          />
          <button className="primary" type="submit" disabled={!canSubmit}>
            {editing ? 'Сохранить' : 'Отправить'}
          </button>
        </div>
      </div>
    </form>
  )
}
