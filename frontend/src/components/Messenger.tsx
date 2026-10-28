import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api } from '../api'
import { initialMessagesState, messagesReducer } from '../messagesState'
import { RealtimeClient, type ConnectionStatus } from '../realtime'
import type { Attachment, Chat, ClientEvent, Message, PendingMessage, User } from '../types'
import { uuid } from '../utils'
import { ChatView } from './ChatView'
import { GroupModal } from './GroupModal'
import { MembersModal } from './MembersModal'
import { Sidebar } from './Sidebar'

interface Props {
  me: User
  onLogout: () => void
  onSessionExpired: () => void
}

const ERROR_TEXT: Record<string, string> = {
  rate_limited: 'слишком часто, подождите немного',
  not_found: 'чат или сообщение недоступны',
}

function sendEvent(pending: PendingMessage): ClientEvent {
  return {
    type: 'message.send',
    chat_id: pending.chatId,
    text: pending.text,
    client_msg_id: pending.clientMsgId,
    reply_to_id: pending.replyTo?.id,
    attachment_ids: pending.attachments.map((a) => a.id),
  }
}

/** Puts the chat with a new message on top and updates its preview. */
function bumpChat(chats: Chat[], message: Message, countAsUnread: boolean): Chat[] {
  const chat = chats.find((c) => c.id === message.chat_id)
  if (!chat) return chats
  if (chat.last_message && chat.last_message.id >= message.id) return chats
  const updated = {
    ...chat,
    last_message: message,
    unread_count: chat.unread_count + (countAsUnread ? 1 : 0),
  }
  return [updated, ...chats.filter((c) => c.id !== chat.id)]
}

function updateChat(chats: Chat[], chatId: number, update: (chat: Chat) => Chat): Chat[] {
  return chats.map((c) => (c.id === chatId ? update(c) : c))
}

function setLastRead(chat: Chat, userId: number, messageId: number): Chat {
  return {
    ...chat,
    members: chat.members.map((m) =>
      m.user.id === userId && (m.last_read_message_id ?? 0) < messageId
        ? { ...m, last_read_message_id: messageId }
        : m,
    ),
  }
}

function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible')
  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])
  return visible
}

export function Messenger({ me, onLogout, onSessionExpired }: Props) {
  const [chats, setChats] = useState<Chat[]>([])
  const [activeChatId, setActiveChatId] = useState<number | null>(null)
  const [messages, dispatch] = useReducer(messagesReducer, initialMessagesState)
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [modal, setModal] = useState<'group' | 'members' | null>(null)
  const pageVisible = usePageVisible()

  const realtime = useRef<RealtimeClient | null>(null)
  // Latest values for the long-lived WebSocket handler.
  const latest = useRef({ messages, activeChatId, chats, pageVisible })
  useEffect(() => {
    latest.current = { messages, activeChatId, chats, pageVisible }
  })

  const applyChats = useCallback((list: Chat[]) => {
    setChats(list)
    // Drop the selection when the chat disappeared (we left or were removed).
    setActiveChatId((id) => (id !== null && !list.some((c) => c.id === id) ? null : id))
  }, [])

  const reloadChats = useCallback(async () => {
    try {
      applyChats(await api.listChats())
    } catch {
      // Offline: the list is reloaded after reconnecting.
    }
  }, [applyChats])

  useEffect(() => {
    api
      .listChats()
      .then(applyChats)
      .catch(() => {})
  }, [applyChats])

  useEffect(() => {
    const client = new RealtimeClient(onSessionExpired)
    realtime.current = client
    let connectedBefore = false
    let reloadTimer: number | undefined

    const scheduleChatsReload = () => {
      window.clearTimeout(reloadTimer)
      reloadTimer = window.setTimeout(() => void reloadChats(), 150)
    }

    const onMessage = (message: Message) => {
      const { chats, activeChatId, pageVisible } = latest.current
      if (!chats.some((c) => c.id === message.chat_id)) scheduleChatsReload()
      const seen = message.chat_id === activeChatId && pageVisible
      setChats((prev) => bumpChat(prev, message, message.sender?.id !== me.id && !seen))
    }

    const unsubscribe = client.subscribe((event) => {
      switch (event.type) {
        case 'auth.ok':
          if (connectedBefore) {
            // Events were missed while offline: refetch instead of trusting the cache.
            dispatch({ type: 'history/invalidate' })
            scheduleChatsReload()
          }
          connectedBefore = true
          for (const pending of latest.current.messages.pending) {
            if (pending.status === 'sending') client.send(sendEvent(pending))
          }
          break
        case 'message.ack':
          dispatch({
            type: 'message/acked',
            clientMsgId: event.client_msg_id,
            message: event.message,
          })
          onMessage(event.message)
          break
        case 'message.new':
          dispatch({ type: 'message/received', message: event.message })
          onMessage(event.message)
          break
        case 'message.updated': {
          const message = event.message
          dispatch({ type: 'message/updated', message })
          setChats((prev) =>
            updateChat(prev, message.chat_id, (c) =>
              c.last_message?.id === message.id ? { ...c, last_message: message } : c,
            ),
          )
          // A deleted unread message no longer counts.
          if (message.deleted) scheduleChatsReload()
          break
        }
        case 'read.updated':
          if (event.user_id === me.id) {
            // Read in another tab.
            scheduleChatsReload()
          } else {
            setChats((prev) =>
              updateChat(prev, event.chat_id, (c) =>
                setLastRead(c, event.user_id, event.last_read_message_id),
              ),
            )
          }
          break
        case 'chat.updated':
          scheduleChatsReload()
          break
        case 'error':
          if (event.client_msg_id) {
            dispatch({
              type: 'pending/status',
              clientMsgId: event.client_msg_id,
              status: 'failed',
              error: ERROR_TEXT[event.code] ?? event.detail,
            })
          }
          break
      }
    })
    const unsubscribeStatus = client.onStatus(setStatus)
    client.start()

    return () => {
      window.clearTimeout(reloadTimer)
      unsubscribe()
      unsubscribeStatus()
      client.stop()
    }
  }, [me.id, onSessionExpired, reloadChats])

  const activeChat = chats.find((c) => c.id === activeChatId) ?? null
  const activeHistory = activeChatId === null ? undefined : messages.byChat[activeChatId]

  // Load the latest page when opening a chat whose history isn't cached.
  const historyLoaded = activeHistory !== undefined
  useEffect(() => {
    if (activeChatId === null || historyLoaded) return
    let cancelled = false
    api
      .messages(activeChatId)
      .then((page) => {
        if (!cancelled)
          dispatch({ type: 'history/loaded', chatId: activeChatId, page, older: false })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [activeChatId, historyLoaded])

  // Mark the open chat as read up to its newest message while the page is visible.
  const newestId = activeHistory?.items.at(-1)?.id
  const myLastRead = activeChat?.members.find((m) => m.user.id === me.id)?.last_read_message_id ?? 0
  useEffect(() => {
    if (activeChatId === null || !pageVisible || newestId === undefined) return
    if (newestId <= myLastRead) return
    const timer = window.setTimeout(() => {
      api
        .markRead(activeChatId, newestId)
        .then(() =>
          setChats((prev) =>
            updateChat(prev, activeChatId, (c) => ({
              ...setLastRead(c, me.id, newestId),
              unread_count: 0,
            })),
          ),
        )
        .catch(() => {})
    }, 300)
    return () => window.clearTimeout(timer)
  }, [activeChatId, newestId, myLastRead, pageVisible, me.id])

  // Unread counter in the tab title; muted chats don't count.
  const totalUnread = chats.reduce((sum, c) => sum + (c.muted ? 0 : c.unread_count), 0)
  useEffect(() => {
    document.title = totalUnread > 0 ? `(${totalUnread}) Мессенджер` : 'Мессенджер'
  }, [totalUnread])

  function selectChat(chatId: number) {
    setActiveChatId(chatId)
    setModal(null)
  }

  async function openDirect(user: User) {
    try {
      const chat = await api.openDirectChat(user.id)
      setChats((prev) => (prev.some((c) => c.id === chat.id) ? prev : [chat, ...prev]))
      selectChat(chat.id)
    } catch {
      // Ignore: the user can retry.
    }
  }

  async function loadMore() {
    if (activeChatId === null || !activeHistory || activeHistory.loadingMore) return
    const oldest = activeHistory.items[0]
    if (!oldest) return
    const chatId = activeChatId
    dispatch({ type: 'history/loadingMore', chatId })
    try {
      const page = await api.messages(chatId, oldest.id)
      dispatch({ type: 'history/loaded', chatId, page, older: true })
    } catch {
      dispatch({ type: 'history/loaded', chatId, page: { items: [], has_more: true }, older: true })
    }
  }

  function send(text: string, attachments: Attachment[], replyTo: Message | null) {
    if (activeChatId === null) return
    const pending: PendingMessage = {
      clientMsgId: uuid(),
      chatId: activeChatId,
      text,
      replyTo,
      attachments,
      createdAt: new Date().toISOString(),
      status: 'sending',
    }
    dispatch({ type: 'pending/added', pending })
    // If offline, it stays pending and is resent after reconnecting.
    realtime.current?.send(sendEvent(pending))
  }

  function retry(clientMsgId: string) {
    const pending = messages.pending.find((p) => p.clientMsgId === clientMsgId)
    if (!pending) return
    dispatch({ type: 'pending/status', clientMsgId, status: 'sending' })
    realtime.current?.send(sendEvent(pending))
  }

  // Edits, deletions and reactions go over REST; the response is applied right away and
  // the message.updated event brings the same change to other members and tabs.
  async function applyUpdate(request: Promise<Message>) {
    dispatch({ type: 'message/updated', message: await request })
  }

  async function toggleMute(chat: Chat) {
    const { muted } = await api.setMuted(chat.id, !chat.muted)
    setChats((prev) => updateChat(prev, chat.id, (c) => ({ ...c, muted })))
  }

  return (
    <div className={`messenger${activeChat ? ' has-active-chat' : ''}`}>
      <Sidebar
        me={me}
        chats={chats}
        activeChatId={activeChatId}
        status={status}
        onSelectChat={selectChat}
        onOpenDirect={openDirect}
        onNewGroup={() => setModal('group')}
        onLogout={onLogout}
      />

      {activeChat ? (
        <ChatView
          key={activeChat.id}
          chat={activeChat}
          me={me}
          history={activeHistory}
          pending={messages.pending.filter((p) => p.chatId === activeChat.id)}
          onSend={send}
          onRetry={retry}
          onLoadMore={loadMore}
          onEdit={(m, text) => applyUpdate(api.editMessage(m.chat_id, m.id, text))}
          onDelete={(m) => applyUpdate(api.deleteMessage(m.chat_id, m.id))}
          onReact={(m, emoji, on) => applyUpdate(api.setReaction(m.chat_id, m.id, emoji, on))}
          onToggleMute={() => toggleMute(activeChat)}
          onOpenMembers={() => setModal('members')}
          onBack={() => setActiveChatId(null)}
        />
      ) : (
        <section className="chat-placeholder">
          <p>Выберите чат или найдите собеседника</p>
        </section>
      )}

      {modal === 'group' && (
        <GroupModal
          me={me}
          onClose={() => setModal(null)}
          onCreated={(chat) => {
            setChats((prev) => [chat, ...prev.filter((c) => c.id !== chat.id)])
            selectChat(chat.id)
            setModal(null)
          }}
        />
      )}
      {modal === 'members' && activeChat && (
        <MembersModal
          chat={activeChat}
          me={me}
          onClose={() => setModal(null)}
          onChanged={reloadChats}
          onLeft={() => {
            setModal(null)
            setActiveChatId(null)
            void reloadChats()
          }}
        />
      )}
    </div>
  )
}
