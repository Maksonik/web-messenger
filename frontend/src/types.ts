// Mirrors the backend's Pydantic schemas (backend/app/schemas).

export interface User {
  id: number
  username: string
  display_name: string
  created_at: string
}

export type MemberRole = 'admin' | 'member'

export interface Member {
  user: User
  role: MemberRole
  joined_at: string
  last_read_message_id: number | null
}

export interface Attachment {
  id: number
  filename: string
  content_type: string
  size: number
  is_image: boolean
  /** Signed link, usable directly in <img src> / <a href>. */
  url: string
}

export interface ReactionGroup {
  emoji: string
  count: number
  user_ids: number[]
}

export interface ReplyPreview {
  id: number
  sender: User | null
  text: string
  deleted: boolean
}

export interface Message {
  id: number
  chat_id: number
  sender: User | null
  text: string
  client_msg_id: string | null
  created_at: string
  edited_at: string | null
  deleted: boolean
  reply_to: ReplyPreview | null
  reactions: ReactionGroup[]
  attachments: Attachment[]
  mention_user_ids: number[]
}

export interface Chat {
  id: number
  type: 'direct' | 'group'
  title: string | null
  created_at: string
  members: Member[]
  muted: boolean
  unread_count: number
  last_message: Message | null
}

export interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface MessagePage {
  items: Message[]
  has_more: boolean
}

export const REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🔥'] as const

// WebSocket events, see backend/app/realtime/events.py.
export type ServerEvent =
  | { type: 'auth.ok'; user: User }
  | { type: 'message.ack'; client_msg_id: string; message: Message }
  | { type: 'message.new'; message: Message }
  | { type: 'message.updated'; message: Message }
  | { type: 'read.updated'; chat_id: number; user_id: number; last_read_message_id: number }
  | { type: 'chat.updated'; chat_id: number }
  | { type: 'error'; code: string; detail: string; client_msg_id?: string }
  | { type: 'pong' }

export type ClientEvent =
  | { type: 'auth'; token: string }
  | {
      type: 'message.send'
      chat_id: number
      text: string
      client_msg_id: string
      reply_to_id?: number
      attachment_ids?: number[]
    }
  | { type: 'ping' }

/** A message typed by the user that the server hasn't confirmed yet. */
export interface PendingMessage {
  clientMsgId: string
  chatId: number
  text: string
  replyTo: Message | null
  attachments: Attachment[]
  createdAt: string
  status: 'sending' | 'failed'
  error?: string
}
