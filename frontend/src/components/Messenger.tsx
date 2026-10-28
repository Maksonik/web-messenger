import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api } from '../api'
import { initialMessagesState, messagesReducer } from '../messagesState'
import { RealtimeClient, type ConnectionStatus } from '../realtime'
import type { Chat, Message, PendingMessage, User } from '../types'
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

function sendEvent(pending: PendingMessage) {
  return {
    type: 'message.send' as const,
    chat_id: pending.chatId,
    text: pending.text,
    client_msg_id: pending.clientMsgId,
  }
}

/** Puts the chat with a new message on top and updates its preview. */
function bumpChat(chats: Chat[], message: Message): Chat[] {
  const chat = chats.find((c) => c.id === message.chat_id)
  if (!chat) return chats
  if (chat.last_message && chat.last_message.id >= message.id) return chats
  return [{ ...chat, last_message: message }, ...chats.filter((c) => c.id !== chat.id)]
}

export function Messenger({ me, onLogout, onSessionExpired }: Props) {
  const [chats, setChats] = useState<Chat[]>([])
  const [activeChatId, setActiveChatId] = useState<number | null>(null)
  const [messages, dispatch] = useReducer(messagesReducer, initialMessagesState)
  const [unread, setUnread] = useState<Record<number, number>>({})
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [modal, setModal] = useState<'group' | 'members' | null>(null)

  const realtime = useRef<RealtimeClient | null>(null)
  // Latest values for the long-lived WebSocket handler.
  const latest = useRef({ messages, activeChatId, chats })
  useEffect(() => {
    latest.current = { messages, activeChatId, chats }
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
      const known = latest.current.chats.some((c) => c.id === message.chat_id)
      if (!known) scheduleChatsReload()
      setChats((prev) => bumpChat(prev, message))
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
          if (
            event.message.sender?.id !== me.id &&
            event.message.chat_id !== latest.current.activeChatId
          ) {
            setUnread((prev) => ({
              ...prev,
              [event.message.chat_id]: (prev[event.message.chat_id] ?? 0) + 1,
            }))
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
              error: event.detail,
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

  function selectChat(chatId: number) {
    setActiveChatId(chatId)
    setModal(null)
    setUnread((prev) => ({ ...prev, [chatId]: 0 }))
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

  function send(text: string) {
    if (activeChatId === null) return
    const pending: PendingMessage = {
      clientMsgId: uuid(),
      chatId: activeChatId,
      text,
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

  return (
    <div className={`messenger${activeChat ? ' has-active-chat' : ''}`}>
      <Sidebar
        me={me}
        chats={chats}
        activeChatId={activeChatId}
        unread={unread}
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
