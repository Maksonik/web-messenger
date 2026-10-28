import type { Attachment, AuthResponse, Chat, Member, Message, MessagePage, User } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// The access token lives only in memory; the refresh token is an httpOnly cookie
// the browser sends to /api/auth/* by itself.
let accessToken: string | null = null
let onUnauthorized: () => void = () => {}

export function getAccessToken(): string | null {
  return accessToken
}

/** Called when the session can't be renewed (refresh token expired or revoked). */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

let refreshInFlight: Promise<AuthResponse | null> | null = null

/**
 * Exchanges the refresh cookie for a new access token.
 * Resolves to null when the session is invalid; rejects on network errors, so a flaky
 * connection doesn't log the user out. Concurrent callers share one request, because
 * every refresh rotates the cookie and a second parallel refresh would be rejected.
 */
export function refreshSession(): Promise<AuthResponse | null> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch('/api/auth/refresh', { method: 'POST' })
      if (!response.ok) {
        accessToken = null
        return null
      }
      return remember(await response.json())
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

function remember(auth: AuthResponse): AuthResponse {
  accessToken = auth.access_token
  return auth
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((e: { msg: string }) => e.msg).join('; ')
    }
  } catch {
    // Not JSON: fall back to the status text.
  }
  return response.statusText || `HTTP ${response.status}`
}

async function request<T>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const headers: Record<string, string> = {}
  const isForm = body instanceof FormData
  // FormData sets its own multipart Content-Type with the boundary.
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  })

  if (response.status === 401 && retry && !path.startsWith('/api/auth/')) {
    if (await refreshSession()) return request(method, path, body, false)
    onUnauthorized()
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  if (response.status === 204) return undefined as T
  return response.json()
}

function query(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined)
  return new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString()
}

export const api = {
  register: (username: string, password: string, displayName?: string) =>
    request<AuthResponse>('POST', '/api/auth/register', {
      username,
      password,
      display_name: displayName || undefined,
    }).then(remember),

  login: (username: string, password: string) =>
    request<AuthResponse>('POST', '/api/auth/login', { username, password }).then(remember),

  logout: () =>
    request<void>('POST', '/api/auth/logout').finally(() => {
      accessToken = null
    }),

  searchUsers: (q: string) => request<User[]>('GET', `/api/users?${query({ q, limit: 10 })}`),

  listChats: () => request<Chat[]>('GET', '/api/chats'),

  openDirectChat: (userId: number) =>
    request<Chat>('POST', '/api/chats/direct', { user_id: userId }),

  createGroup: (title: string, memberIds: number[]) =>
    request<Chat>('POST', '/api/chats/group', { title, member_ids: memberIds }),

  renameChat: (chatId: number, title: string) =>
    request<Chat>('PATCH', `/api/chats/${chatId}`, { title }),

  addMember: (chatId: number, userId: number) =>
    request<Member>('POST', `/api/chats/${chatId}/members`, { user_id: userId }),

  removeMember: (chatId: number, userId: number) =>
    request<void>('DELETE', `/api/chats/${chatId}/members/${userId}`),

  messages: (chatId: number, beforeId?: number, limit = 50) =>
    request<MessagePage>(
      'GET',
      `/api/chats/${chatId}/messages?${query({ before_id: beforeId, limit })}`,
    ),

  searchMessages: (chatId: number, q: string, beforeId?: number) =>
    request<MessagePage>(
      'GET',
      `/api/chats/${chatId}/messages/search?${query({ q, before_id: beforeId, limit: 20 })}`,
    ),

  editMessage: (chatId: number, messageId: number, text: string) =>
    request<Message>('PATCH', `/api/chats/${chatId}/messages/${messageId}`, { text }),

  deleteMessage: (chatId: number, messageId: number) =>
    request<Message>('DELETE', `/api/chats/${chatId}/messages/${messageId}`),

  setReaction: (chatId: number, messageId: number, emoji: string, on: boolean) =>
    request<Message>(
      on ? 'PUT' : 'DELETE',
      `/api/chats/${chatId}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`,
    ),

  markRead: (chatId: number, messageId: number) =>
    request<{ last_read_message_id: number }>('POST', `/api/chats/${chatId}/read`, {
      message_id: messageId,
    }),

  setMuted: (chatId: number, muted: boolean) =>
    request<{ muted: boolean }>('PUT', `/api/chats/${chatId}/mute`, { muted }),

  uploadAttachment: (chatId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Attachment>('POST', `/api/chats/${chatId}/attachments`, form)
  },
}
