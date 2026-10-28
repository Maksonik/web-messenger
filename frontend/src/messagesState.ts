import type { Message, MessagePage, PendingMessage } from './types'

export interface ChatHistory {
  /** Server-confirmed messages, ascending by id. */
  items: Message[]
  hasMore: boolean
  loadingMore: boolean
}

export interface MessagesState {
  /** Loaded histories; a chat without an entry hasn't been loaded yet. */
  byChat: Record<number, ChatHistory>
  pending: PendingMessage[]
}

export type MessagesAction =
  | { type: 'history/loaded'; chatId: number; page: MessagePage; older: boolean }
  | { type: 'history/loadingMore'; chatId: number }
  | { type: 'history/invalidate' }
  | { type: 'pending/added'; pending: PendingMessage }
  | {
      type: 'pending/status'
      clientMsgId: string
      status: PendingMessage['status']
      error?: string
    }
  | { type: 'message/acked'; clientMsgId: string; message: Message }
  | { type: 'message/received'; message: Message }
  /** Edited, deleted or reactions changed: replaced in place, never inserted. */
  | { type: 'message/updated'; message: Message }

export const initialMessagesState: MessagesState = { byChat: {}, pending: [] }

function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  const byId = new Map(existing.map((m) => [m.id, m]))
  for (const message of incoming) byId.set(message.id, message)
  return [...byId.values()].sort((a, b) => a.id - b.id)
}

function addMessage(state: MessagesState, message: Message): MessagesState {
  // Confirmation of our own pending message, whichever of ack/new arrives first.
  const pending = state.pending.filter((p) => p.clientMsgId !== message.client_msg_id)
  const history = state.byChat[message.chat_id]
  // Histories that aren't loaded will fetch the message when the chat is opened.
  if (!history) return { ...state, pending }
  return {
    pending,
    byChat: {
      ...state.byChat,
      [message.chat_id]: { ...history, items: mergeMessages(history.items, [message]) },
    },
  }
}

export function messagesReducer(state: MessagesState, action: MessagesAction): MessagesState {
  switch (action.type) {
    case 'history/loaded': {
      const current = state.byChat[action.chatId]
      const items = mergeMessages(current?.items ?? [], action.page.items)
      const hasMore = action.older || !current ? action.page.has_more : current.hasMore
      return {
        ...state,
        byChat: { ...state.byChat, [action.chatId]: { items, hasMore, loadingMore: false } },
      }
    }
    case 'history/loadingMore': {
      const current = state.byChat[action.chatId]
      if (!current) return state
      return {
        ...state,
        byChat: { ...state.byChat, [action.chatId]: { ...current, loadingMore: true } },
      }
    }
    case 'history/invalidate':
      // After a reconnect we may have missed messages; merging a fresh page into the
      // old one could leave a gap, so drop cached histories and reload on demand.
      return { ...state, byChat: {} }
    case 'pending/added':
      return { ...state, pending: [...state.pending, action.pending] }
    case 'pending/status':
      return {
        ...state,
        pending: state.pending.map((p) =>
          p.clientMsgId === action.clientMsgId
            ? { ...p, status: action.status, error: action.error }
            : p,
        ),
      }
    case 'message/acked':
    case 'message/received':
      return addMessage(state, action.message)
    case 'message/updated': {
      const updated = action.message
      const history = state.byChat[updated.chat_id]
      if (!history) return state
      const items = history.items.map((m) => {
        if (m.id === updated.id) return updated
        // Keep quotes of the changed message in sync (edited text, "deleted").
        if (m.reply_to?.id === updated.id) {
          return {
            ...m,
            reply_to: { ...m.reply_to, text: updated.text, deleted: updated.deleted },
          }
        }
        return m
      })
      return { ...state, byChat: { ...state.byChat, [updated.chat_id]: { ...history, items } } }
    }
  }
}
