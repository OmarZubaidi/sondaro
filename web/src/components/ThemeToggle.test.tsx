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
const toggle = () => screen.getByRole('button', { name: /^Theme/ })

beforeEach(() => {
  osDark = false
  vi.stubGlobal('matchMedia', () => ({
    get matches() {
      return osDark
    },
    addEventListener: (_: string, listener: () => void) => osListeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => osListeners.delete(listener),
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
  osListeners.clear()
  localStorage.clear()
})

describe('ThemeToggle', () => {
  it('follows the system when nothing is remembered', () => {
    osDark = true
    render(<ThemeToggle />)
    expect(toggle()).toHaveAccessibleName('Theme: system')
    expect(pageTheme()).toBe('dark')

    setOs(false)
    expect(pageTheme()).toBe('light')
  })

  it('starts from a choice remembered on an earlier visit, and ignores the system', () => {
    localStorage.setItem('theme', 'light')
    osDark = true
    render(<ThemeToggle />)
    expect(toggle()).toHaveAccessibleName('Theme: light')
    expect(pageTheme()).toBe('light')

    setOs(false)
    setOs(true)
    expect(pageTheme()).toBe('light')
  })

  it('cycles to the other theme, then the system’s own, then back to the system', async () => {
    render(<ThemeToggle />)

    await userEvent.click(toggle())
    expect(toggle()).toHaveAccessibleName('Theme: dark')
    expect(pageTheme()).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')

    await userEvent.click(toggle())
    expect(toggle()).toHaveAccessibleName('Theme: light')
    expect(pageTheme()).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')

    await userEvent.click(toggle())
    expect(toggle()).toHaveAccessibleName('Theme: system')
    expect(localStorage.getItem('theme')).toBeNull()
    setOs(true)
    expect(pageTheme()).toBe('dark')
  })

  it('goes light first on a dark system', async () => {
    osDark = true
    render(<ThemeToggle />)
    await userEvent.click(toggle())
    expect(toggle()).toHaveAccessibleName('Theme: light')
    expect(pageTheme()).toBe('light')
  })
})
