import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ShowCard } from './ShowCard'
import type { Show } from '../lib/types'

function makeShow(overrides: Partial<Show> = {}): Show {
  return {
    id: 'ticketmaster:1',
    artist: 'The National',
    listens: 4210,
    score: 0.64,
    affinity: 1,
    date_fit: 1,
    reach_fit: 0.64,
    flags: [],
    reasons: ['4,210 scrobbles'],
    drive_hours: 2.6,
    miles: 165,
    date: '2026-09-08',
    time: '20:00',
    venue: 'The Fillmore',
    city: 'Fairview',
    region: 'KS',
    country: 'US',
    lat: 37.5,
    lon: -97.0,
    url: 'https://example.test/1',
    provider: 'ticketmaster',
    ...overrides,
  }
}

describe('ShowCard', () => {
  it('renders the artist, place and score', () => {
    render(<ShowCard show={makeShow()} />)

    expect(screen.getByText('The National')).toBeInTheDocument()
    expect(screen.getByText(/The Fillmore, Fairview, KS/)).toBeInTheDocument()
    expect(screen.getByTestId('score-value')).toHaveTextContent('0.64')
  })

  it('renders drive time as hours and minutes, not a decimal', () => {
    render(<ShowCard show={makeShow({ drive_hours: 2.6 })} />)
    expect(screen.getByText(/2h 36m drive/)).toBeInTheDocument()
  })

  it('marks an estimated drive time with a tilde', () => {
    render(
      <ShowCard show={makeShow({ flags: ['estimated drive time'] })} />,
    )
    expect(screen.getByText(/~2h 36m drive/)).toBeInTheDocument()
  })

  it('shows every flag it is given', () => {
    render(
      <ShowCard
        show={makeShow({
          flags: ['not on your itinerary (Switzerland)', 'outside your dates'],
        })}
      />,
    )
    expect(screen.getByText('not on your itinerary (Switzerland)')).toBeInTheDocument()
    expect(screen.getByText('outside your dates')).toBeInTheDocument()
  })

  it('does not badge a show for merely being far away', () => {
    // a long drive sinks on score alone; a badge would draw the eye to the
    // thing you are least likely to do
    render(<ShowCard show={makeShow({ drive_hours: 6, score: 0.06, flags: [] })} />)
    expect(screen.queryByText(/major planning/)).not.toBeInTheDocument()
  })

  it('is not interactive unless a toggle handler is supplied', () => {
    render(<ShowCard show={makeShow()} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('toggles selection when tapped', async () => {
    const onToggle = vi.fn()
    const show = makeShow()
    render(<ShowCard show={show} onToggle={onToggle} />)

    await userEvent.click(screen.getByRole('button'))

    expect(onToggle).toHaveBeenCalledWith(show)
  })

  it('reports its selected state to assistive tech', () => {
    render(<ShowCard show={makeShow()} selected onToggle={() => {}} />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })

  it('omits the drive line when there is no drive time', () => {
    render(<ShowCard show={makeShow({ drive_hours: null, miles: null })} />)
    expect(screen.queryByText(/drive/)).not.toBeInTheDocument()
  })
})
