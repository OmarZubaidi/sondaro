import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TripForm, fieldsFromTrip, toPayload } from './TripForm'
import type { Trip } from '../lib/types'

const TRIP: Trip = {
  id: 1,
  name: 'Europe',
  countries: ['FR', 'ES'],
  cities: ['Lyon'],
  start_date: '2026-09-20',
  end_date: '2026-09-30',
  flex_before: 3,
  flex_after: 2,
  strict_dates: false,
  scanned_at: null,
}

describe('fieldsFromTrip / toPayload', () => {
  it('round-trips a trip without losing anything', () => {
    expect(toPayload(fieldsFromTrip(TRIP))).toMatchObject({
      name: 'Europe',
      countries: ['FR', 'ES'],
      cities: ['Lyon'],
      start_date: '2026-09-20',
      end_date: '2026-09-30',
      flex_before: 3,
      flex_after: 2,
      strict_dates: false,
    })
  })

  it('upper-cases country codes and trims whitespace', () => {
    const payload = toPayload({ ...fieldsFromTrip(TRIP), countries: ' fr ,  it ' })
    expect(payload.countries).toEqual(['FR', 'IT'])
  })

  it('treats an emptied city list as no cities named', () => {
    const payload = toPayload({ ...fieldsFromTrip(TRIP), cities: '  ,  ' })
    expect(payload.cities).toEqual([])
  })
})

describe('TripForm', () => {
  const noop = () => {}

  it('opens pre-filled when editing an existing trip', () => {
    render(
      <TripForm
        initial={fieldsFromTrip(TRIP)}
        countries={[]}
        submitLabel="Save changes"
        onSubmit={noop}
      />,
    )

    expect(screen.getByLabelText(/^Name$/)).toHaveValue('Europe')
    expect(screen.getByLabelText(/Countries/)).toHaveValue('FR, ES')
    expect(screen.getByLabelText(/Cities/)).toHaveValue('Lyon')
  })

  it('submits what you edited', async () => {
    const onSubmit = vi.fn()
    render(
      <TripForm
        initial={fieldsFromTrip(TRIP)}
        countries={[]}
        submitLabel="Save changes"
        onSubmit={onSubmit}
      />,
    )

    const cities = screen.getByLabelText(/Cities/)
    await userEvent.clear(cities)
    await userEvent.type(cities, 'Lyon, Barcelona')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ cities: 'Lyon, Barcelona' }),
    )
  })

  it('hides the slack fields when dates are strict', async () => {
    render(
      <TripForm
        initial={fieldsFromTrip(TRIP)}
        countries={[]}
        submitLabel="Save"
        onSubmit={noop}
      />,
    )

    expect(screen.getByLabelText(/slack before/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText(/Strict dates/))
    expect(screen.queryByLabelText(/slack before/)).not.toBeInTheDocument()
  })

  it('offers a cancel only when editing', () => {
    const { rerender } = render(
      <TripForm
        initial={fieldsFromTrip(TRIP)}
        countries={[]}
        submitLabel="Create trip"
        onSubmit={noop}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()

    rerender(
      <TripForm
        initial={fieldsFromTrip(TRIP)}
        countries={[]}
        submitLabel="Save changes"
        onSubmit={noop}
        onCancel={noop}
      />,
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('disables submission while saving', () => {
    render(
      <TripForm
        initial={fieldsFromTrip(TRIP)}
        countries={[]}
        submitLabel="Save changes"
        busy
        onSubmit={noop}
      />,
    )
    expect(screen.getByRole('button', { name: /Saving/ })).toBeDisabled()
  })
})
