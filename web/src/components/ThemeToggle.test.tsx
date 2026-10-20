import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThemeToggle } from './ThemeToggle'

let osDark = false
const osListeners = new Set<() => void>()

function setOs(dark: boolean) {
  osDark = dark
  act(() => osListeners.forEach((listener) => listener()))
}

const pageTheme = () => document.documentElement.dataset.theme
const toggle = () => screen.getByRole('button', { name: 'Dark mode' })

beforeEach(() => {
  osDark = false
  vi.stubGlobal('matchMedia', () => ({
    get matches() {
      return osDark
    },
    addEventListener: (_: string, listener: () => void) => osListeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => osListeners.delete(listener),
  }))
  document.documentElement.dataset.theme = 'light'
})

afterEach(() => {
  vi.unstubAllGlobals()
  osListeners.clear()
  localStorage.clear()
})

describe('ThemeToggle', () => {
  it('starts from the theme index.html set before the first paint', () => {
    document.documentElement.dataset.theme = 'dark'
    render(<ThemeToggle />)
    expect(toggle()).toHaveAttribute('aria-pressed', 'true')
  })

  it('flips the page theme and remembers the choice', async () => {
    render(<ThemeToggle />)

    await userEvent.click(toggle())
    expect(pageTheme()).toBe('dark')
    expect(toggle()).toHaveAttribute('aria-pressed', 'true')
    expect(localStorage.getItem('theme')).toBe('dark')

    await userEvent.click(toggle())
    expect(pageTheme()).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('follows the OS until a theme is picked', async () => {
    render(<ThemeToggle />)
    setOs(true)
    expect(pageTheme()).toBe('dark')

    await userEvent.click(toggle())
    setOs(false)
    setOs(true)
    expect(pageTheme()).toBe('light')
  })

  it('ignores the OS when a choice was remembered from an earlier visit', () => {
    localStorage.setItem('theme', 'light')
    render(<ThemeToggle />)
    setOs(true)
    expect(pageTheme()).toBe('light')
  })
})
