interface Props {
  name: string
  /** Stable seed for the color (user or chat id). */
  seed: number
  size?: number
}

export function Avatar({ name, seed, size = 40 }: Props) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('')
  const hue = (seed * 67) % 360
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.4,
        background: `hsl(${hue} 55% 52%)`,
      }}
      aria-hidden
    >
      {initials || '?'}
    </div>
  )
}
