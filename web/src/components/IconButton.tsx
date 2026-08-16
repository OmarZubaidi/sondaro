import type { ReactNode } from 'react'

/** Small square actions that sit beside a heading rather than forming a row of
 *  full-size buttons. The label is always present for screen readers and as a
 *  tooltip; only the glyph is drawn. */
interface Props {
  label: string
  icon: ReactNode
  onClick?: () => void
  href?: string
  disabled?: boolean
  tone?: 'default' | 'danger'
}

export function IconButton({ label, icon, onClick, href, disabled, tone = 'default' }: Props) {
  const className = `icon-button${tone === 'danger' ? ' danger' : ''}`

  if (href) {
    return (
      <a className={className} href={href} title={label} aria-label={label}>
        {icon}
      </a>
    )
  }
  return (
    <button
      type="button"
      className={className}
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
    >
      {icon}
    </button>
  )
}

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" {...stroke}>
      {children}
    </svg>
  )
}

export const EditIcon = () => (
  <Svg>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </Svg>
)

export const RescanIcon = () => (
  <Svg>
    <path d="M21 12a9 9 0 1 1-3-6.7" />
    <path d="M21 3v6h-6" />
  </Svg>
)

export const CalendarIcon = () => (
  <Svg>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M8 3v4M16 3v4M3 11h18" />
  </Svg>
)

export const TrashIcon = () => (
  <Svg>
    <path d="M4 7h16" />
    <path d="M10 11v6M14 11v6" />
    <path d="M6 7l1 13h10l1-13" />
    <path d="M9 7V4h6v3" />
  </Svg>
)
