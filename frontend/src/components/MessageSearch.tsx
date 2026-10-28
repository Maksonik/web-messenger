import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Message } from '../types'
import { formatShortDate, useDebounced } from '../utils'

interface Props {
  chatId: number
  onClose: () => void
}

function Highlight({ text, query }: { text: string; query: string }) {
  const index = text.toLowerCase().indexOf(query.toLowerCase())
  if (!query || index < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + query.length)}</mark>
      {text.slice(index + query.length)}
    </>
  )
}

export function MessageSearch({ chatId, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Message[]>([])
  const [hasMore, setHasMore] = useState(false)
  // The query the current results belong to; while it differs, a search is in flight.
  const [resultsFor, setResultsFor] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const debounced = useDebounced(query.trim())
  const loading = debounced !== resultsFor || loadingMore

  useEffect(() => {
    if (!debounced) return
    let cancelled = false
    const apply = (items: Message[], more: boolean) => {
      if (cancelled) return
      setResults(items)
      setHasMore(more)
      setResultsFor(debounced)
    }
    api
      .searchMessages(chatId, debounced)
      .then((page) => apply(page.items, page.has_more))
      .catch(() => apply([], false))
    return () => {
      cancelled = true
    }
  }, [chatId, debounced])

  async function loadMore() {
    const last = results.at(-1)
    if (!last) return
    setLoadingMore(true)
    try {
      const page = await api.searchMessages(chatId, debounced, last.id)
      setResults((prev) => [...prev, ...page.items])
      setHasMore(page.has_more)
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <aside className="search-panel">
      <div className="search-panel-header">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск по сообщениям"
          autoFocus
        />
        <button className="icon-button" onClick={onClose} aria-label="Закрыть поиск">
          ✕
        </button>
      </div>
      <ul className="search-results">
        {debounced && !loading && results.length === 0 && (
          <li className="empty-hint">Ничего не найдено</li>
        )}
        {debounced &&
          results.map((message) => (
            <li key={message.id} className="search-result">
              <div className="search-result-top">
                <strong>{message.sender?.display_name ?? 'Удалённый пользователь'}</strong>
                <time className="muted">{formatShortDate(message.created_at)}</time>
              </div>
              <div>
                <Highlight text={message.text} query={debounced} />
              </div>
            </li>
          ))}
        {debounced && hasMore && (
          <li>
            <button className="load-more" onClick={loadMore} disabled={loading}>
              Ещё результаты
            </button>
          </li>
        )}
      </ul>
    </aside>
  )
}
