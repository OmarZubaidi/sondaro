import { useEffect, useState } from 'react'
import { MoonIcon, SunIcon, SystemIcon } from './IconButton'

// index.html reads both too, to set the theme before the first paint
const STORAGE_KEY = 'theme'
const OS_DARK = '(prefers-color-scheme: dark)'

type Theme = 'light' | 'dark'
type Mode = Theme | 'system'

const MODES = {
  system: { label: 'Theme: system', icon: <SystemIcon /> },
  light: { label: 'Theme: light', icon: <SunIcon /> },
  dark: { label: 'Theme: dark', icon: <MoonIcon /> },
}

function remembered(): Mode {
  let stored = null
  try {
    stored = localStorage.getItem(STORAGE_KEY)
  } catch {
    // blocked storage reads as no choice
  }
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

function remember(mode: Mode) {
  try {
    if (mode === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // the theme still changes for this visit, it just isn't remembered
  }
}

/** From the system setting, the first click always changes the page; the
 *  next pins the system's own theme, and the third goes back to following it. */
function nextMode(mode: Mode, os: Theme): Mode {
  if (mode === 'system') return os === 'dark' ? 'light' : 'dark'
  return mode === os ? 'system' : os
}

export function ThemeToggle() {
  const [mode, setMode] = useState(remembered)
  const [os, setOs] = useState<Theme>(() =>
    window.matchMedia(OS_DARK).matches ? 'dark' : 'light',
  )
  const theme = mode === 'system' ? os : mode

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const query = window.matchMedia(OS_DARK)
    const follow = () => setOs(query.matches ? 'dark' : 'light')
    query.addEventListener('change', follow)
    return () => query.removeEventListener('change', follow)
  }, [])

  function cycle() {
    const next = nextMode(mode, os)
    setMode(next)
    remember(next)
  }

  const { label, icon } = MODES[mode]
  return (
    <button
      type="button"
      className="icon-button on-ink"
      aria-label={label}
      title={label}
      onClick={cycle}
    >
      {icon}
    </button>
  )
}
