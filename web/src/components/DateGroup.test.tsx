import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DateGroup } from './DateGroup'
import type { Show } from '../lib/types'

function show(id: string, artist: string, score: number): Show {
  return {
    id,
    artist,
    listens: 10,
    score,
    affinity: score,
    date_fit: 1,
    reach_fit: 1,
    flags: [],
    reasons: [],
    drive_hours: 1,
    miles: 40,
    date: '2026-09-12',
    time: '20:00',
    venue: 'Somewhere',
    city: 'Springfield',
    region: 'KS',
    country: 'US',
    lat: 38.2,
    lon: -95.2,
    url: null,
    provider: 'ticketmaster',
  purchased: false,
  }
}

describe('DateGroup', () => {
  it('lists every option for the night, best first', () => {
    render(
      <DateGroup
        date="2026-09-12"
        shows={[show('a', 'Middling', 0.3), show('b', 'Excellent', 0.9)]}
      />,
    )

    const artists = screen.getAllByText(/Middling|Excellent/).map((n) => n.textContent)
    expect(artists).toEqual(['Excellent', 'Middling'])
  })

  it('says how many options there are when there is a clash', () => {
    render(
      <DateGroup
        date="2026-09-12"
        shows={[show('a', 'One', 0.3), show('b', 'Two', 0.9)]}
      />,
    )
    expect(screen.getByText(/2 options/)).toBeInTheDocument()
  })

  it('does not label a single show as a choice', () => {
    render(<DateGroup date="2026-09-12" shows={[show('a', 'Only', 0.5)]} />)
    expect(screen.queryByText(/options/)).not.toBeInTheDocument()
  })

  it('renders the date as YYYY-MM-DD', () => {
    render(<DateGroup date="2026-09-12" shows={[show('a', 'Only', 0.5)]} />)
    const heading = screen.getByRole('heading')
    expect(within(heading).getByText('2026-09-12')).toBeInTheDocument()
  })

  it('still marks a weekend, which is the part of the weekday that matters', () => {
    render(<DateGroup date="2026-09-12" shows={[show('a', 'Only', 0.5)]} />)
    expect(screen.getByText('2026-09-12')).toHaveClass('weekend')
  })
})
