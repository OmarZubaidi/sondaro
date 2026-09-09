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
    km: 265,
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
  purchased: false,
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

  it('says the date and the time the doors open', () => {
    render(<ShowCard show={makeShow()} />)
    expect(screen.getByText('2026-09-08')).toBeInTheDocument()
    expect(screen.getByText('20:00')).toBeInTheDocument()
  })

  it('shows the date alone when the doors are still TBA', () => {
    render(<ShowCard show={makeShow({ time: null })} />)
    expect(screen.getByText('2026-09-08')).toBeInTheDocument()
    expect(screen.queryByText(/\d\d:\d\d/)).not.toBeInTheDocument()
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

  // the card names itself after the act, so queries say which button they mean
  const selectButton = () => screen.queryByRole('button', { name: /The National/ })
  const ticketButton = () => screen.getByRole('button', { name: /bought|going/ })

  it('is not selectable unless a toggle handler is supplied', () => {
    render(<ShowCard show={makeShow()} />)
    expect(selectButton()).not.toBeInTheDocument()
  })

  it('toggles selection when tapped', async () => {
    const onToggle = vi.fn()
    const show = makeShow()
    render(<ShowCard show={show} onToggle={onToggle} />)

    await userEvent.click(selectButton()!)

    expect(onToggle).toHaveBeenCalledWith(show)
  })

  it('reports its selected state to assistive tech', () => {
    render(<ShowCard show={makeShow()} selected onToggle={() => {}} />)
    expect(selectButton()).toHaveAttribute('aria-pressed', 'true')
  })

  it('offers to mark a ticket as bought, and says so once it is', () => {
    render(<ShowCard show={makeShow({ purchased: true })} />)

    expect(ticketButton()).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('ticket bought')).toBeInTheDocument()
  })

  it('labels which trip a show turned up for', () => {
    render(<ShowCard show={makeShow({ trips: [{ id: 1, name: 'Summer in Europe' }] })} />)
    expect(screen.getByText('Summer in Europe')).toBeInTheDocument()
  })

  it('leads with the venue when the list is already grouped by act', () => {
    render(<ShowCard show={makeShow()} showArtist={false} />)

    expect(screen.queryByText('The National')).not.toBeInTheDocument()
    expect(screen.getByText('The Fillmore, Fairview, KS')).toBeInTheDocument()
  })

  it('drops the country when the list is already grouped by country', () => {
    render(
      <ShowCard
        show={makeShow({ venue: 'Budokan', city: 'Tokyo', region: null, country: 'JP' })}
        showCountry={false}
      />,
    )

    expect(screen.getByText('Budokan, Tokyo')).toBeInTheDocument()
  })

  it('keeps the region when the country is grouped away', () => {
    // "Fairview" on its own is ambiguous in the US; "Fairview, KS" is not
    render(<ShowCard show={makeShow()} showCountry={false} />)

    expect(screen.getByText('The Fillmore, Fairview, KS')).toBeInTheDocument()
  })

  it('omits the drive line when there is no drive time', () => {
    render(<ShowCard show={makeShow({ drive_hours: null, km: null })} />)
    expect(screen.queryByText(/drive/)).not.toBeInTheDocument()
  })
})
