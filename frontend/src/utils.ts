import { useEffect, useState } from 'react'
import type { Chat, User } from './types'

/** RFC 4122 v4 UUID. crypto.randomUUID only exists in secure contexts (HTTPS/localhost). */
export function uuid(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

/** Time for today's messages, a date for older ones. */
export function formatShortDate(iso: string): string {
  const date = new Date(iso)
  if (date.toDateString() === new Date().toDateString()) return formatTime(iso)
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

export function chatPeer(chat: Chat, meId: number): User | undefined {
  return chat.members.find((m) => m.user.id !== meId)?.user
}

/** Avatar color seed: the peer for direct chats, so it matches the user's avatar elsewhere. */
export function chatAvatarSeed(chat: Chat, meId: number): number {
  return chat.type === 'direct' ? (chatPeer(chat, meId)?.id ?? chat.id) : chat.id
}

export function chatTitle(chat: Chat, meId: number): string {
  if (chat.type === 'group') return chat.title ?? 'Группа'
  return chatPeer(chat, meId)?.display_name ?? 'Удалённый пользователь'
}

export function pluralMembers(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  const word =
    mod10 === 1 && mod100 !== 11
      ? 'участник'
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? 'участника'
        : 'участников'
  return `${count} ${word}`
}

export function useDebounced<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}
