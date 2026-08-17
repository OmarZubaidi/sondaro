import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CalendarLink } from './CalendarLink'

describe('CalendarLink', () => {
  it('hands over a URL to subscribe with, not a file to download', async () => {
    render(<CalendarLink />)
    await userEvent.click(screen.getByRole('button', { name: /calendar subscription/i }))

    const field = screen.getByLabelText('Subscription URL') as HTMLInputElement
    expect(field.value).toMatch(/\/sondaro\.ics$/)
    expect(field).toHaveAttribute('readonly')
  })

  it('offers a webcal handoff, which is what actually subscribes', async () => {
    render(<CalendarLink />)
    await userEvent.click(screen.getByRole('button', { name: /calendar subscription/i }))

    expect(screen.getByRole('link', { name: /open in calendar/i })).toHaveAttribute(
      'href',
      expect.stringContaining('webcal://'),
    )
  })

  it('shows the URL even before you press copy, because http has no clipboard', async () => {
    // the tailnet serves this over plain http, where navigator.clipboard is
    // undefined — the field being present and selectable is the real fallback
    render(<CalendarLink />)
    await userEvent.click(screen.getByRole('button', { name: /calendar subscription/i }))

    expect(screen.getByLabelText('Subscription URL')).toBeVisible()
  })

  it('stays out of the way until asked for', () => {
    render(<CalendarLink />)

    expect(screen.queryByLabelText('Subscription URL')).not.toBeInTheDocument()
  })
})
