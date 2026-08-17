import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CalendarSubscription } from './CalendarSubscription'

const url = () => (screen.getByLabelText('Subscription URL') as HTMLInputElement).value

describe('CalendarSubscription', () => {
  it('points at the tailnet, not at wherever you happen to be browsing', () => {
    render(<CalendarSubscription tailnetUrl="https://sondaro.example-tailnet.ts.net" />)

    expect(url()).toBe('https://sondaro.example-tailnet.ts.net/sondaro.ics')
  })

  it('offers a webcal handoff, which is what actually subscribes', () => {
    render(<CalendarSubscription tailnetUrl="https://sondaro.example-tailnet.ts.net" />)

    expect(screen.getByRole('link', { name: /open in calendar/i })).toHaveAttribute(
      'href',
      'webcal://sondaro.example-tailnet.ts.net/sondaro.ics',
    )
  })

  it('falls back to the current address and says the link is local-only', () => {
    // silently handing over a LAN url is the failure worth avoiding: it works
    // on the machine you set it up on and nowhere else, months later
    render(<CalendarSubscription tailnetUrl="" />)

    expect(url()).toMatch(/^http:\/\/localhost/)
    expect(screen.getByText(/won't resolve off your network/i)).toBeInTheDocument()
  })

  it('does not warn when the tailnet address is known', () => {
    render(<CalendarSubscription tailnetUrl="https://sondaro.example-tailnet.ts.net" />)

    expect(screen.queryByText(/won't resolve/i)).not.toBeInTheDocument()
  })

  it('shows the url as selectable text, since http has no clipboard', () => {
    render(<CalendarSubscription tailnetUrl="https://sondaro.example-tailnet.ts.net" />)

    expect(screen.getByLabelText('Subscription URL')).toHaveAttribute('readonly')
  })
})
