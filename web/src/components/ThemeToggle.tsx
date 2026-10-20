import { useEffect, useRef, useState } from 'react'
import { MoonIcon } from './IconButton'

// index.html reads both too, to set the theme before the first paint
const STORAGE_KEY = 'theme'
const OS_DARK = '(prefers-color-scheme: dark)'

type Theme = 'light' | 'dark'

const root = document.documentElement

function storedTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

/** Follows the OS until the first click, then keeps whichever theme was picked. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() =>
    root.dataset.theme === 'dark' ? 'dark' : 'light',
  )
  const picked = useRef(storedTheme() !== null)

  useEffect(() => {
    root.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const os = window.matchMedia(OS_DARK)
    const follow = () => {
      if (!picked.current) setTheme(os.matches ? 'dark' : 'light')
    }
    os.addEventListener('change', follow)
    return () => os.removeEventListener('change', follow)
  }, [])

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    picked.current = true
    setTheme(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // the theme still changes for this visit, it just isn't remembered
    }
  }

  return (
    <button
      type="button"
      className="icon-button on-ink"
      aria-label="Dark mode"
      title="Dark mode"
      aria-pressed={theme === 'dark'}
      onClick={toggle}
    >
      <MoonIcon />
    </button>
  )
}
