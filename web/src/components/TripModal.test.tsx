import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TripModal, type TripPrefill } from './TripModal'
import { api } from '../lib/api'
import type { Trip } from '../lib/types'

const COUNTRIES = [
  { code: 'IE', name: 'Ireland' },
  { code: 'GB', name: 'United Kingdom' },
  { code: 'FR', name: 'France' },
  { code: 'JP', name: 'Japan' },
  { code: 'KR', name: 'South Korea' },
]

const PREFILL: TripPrefill = {
  name: 'Dublin · Glasgow',
  start_date: '2027-02-12',
  end_date: '2027-02-17',
  countries: ['IE', 'GB', 'FR'],
  cities: [
    { country: 'IE', city: 'Dublin' },
    { country: 'GB', city: 'Glasgow' },
  ],
}

const TRIP: Trip = {
  id: 7,
  name: 'Japan spring',
  legs: [
    { country: 'JP', city: 'Tokyo', start_date: '2027-04-02', end_date: '2027-04-07' },
    { country: 'KR', city: null, start_date: null, end_date: null },
  ],
  countries: ['JP', 'KR'],
  cities: ['Tokyo'],
  start_date: '2027-04-02',
  end_date: '2027-04-14',
  flex_before: 2,
  flex_after: 2,
  strict_dates: false,
  scanned_at: null,
}

function open(props: { trip?: Trip; prefill?: TripPrefill }) {
  const onSaved = vi.fn()
  render(<TripModal {...props} countries={COUNTRIES} onClose={() => {}} onSaved={onSaved} />)
  return { onSaved }
}

const chip = (label: string) => screen.queryByRole('button', { name: `Remove ${label}` })

describe('TripModal', () => {
  it('opens filled in from a prefill', () => {
    open({ prefill: PREFILL })

    expect(screen.getByRole('dialog', { name: 'New trip' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Dublin · Glasgow')
    expect(screen.getByLabelText('First day')).toHaveValue('2027-02-12')
    expect(screen.getByLabelText('Last day')).toHaveValue('2027-02-17')
    for (const label of ['Ireland', 'United Kingdom', 'France', 'Dublin', 'Glasgow']) {
      expect(chip(label)).toBeInTheDocument()
    }
  })

  it('creates the prefilled trip, leaving a country with no city open', async () => {
    const created = vi.spyOn(api, 'createTrip').mockResolvedValue(TRIP)
    const { onSaved } = open({ prefill: PREFILL })

    await userEvent.click(screen.getByRole('button', { name: 'Create trip' }))

    expect(created).toHaveBeenCalledWith({
      name: 'Dublin · Glasgow',
      start_date: '2027-02-12',
      end_date: '2027-02-17',
      strict_dates: false,
      flex_before: 3,
      flex_after: 3,
      legs: [
        { country: 'IE', city: 'Dublin', start_date: null, end_date: null },
        { country: 'GB', city: 'Glasgow', start_date: null, end_date: null },
        { country: 'FR', city: null, start_date: null, end_date: null },
      ],
    })
    expect(onSaved).toHaveBeenCalled()
  })

  it('keeps a prefilled city’s country even when the prefill forgot it', () => {
    open({ prefill: { ...PREFILL, countries: [] } })

    expect(chip('Ireland')).toBeInTheDocument()
    expect(chip('United Kingdom')).toBeInTheDocument()
    expect(chip('Dublin')).toBeInTheDocument()
  })

  it('edits an existing trip as before, ignoring any prefill', async () => {
    const updated = vi.spyOn(api, 'updateTrip').mockResolvedValue({
      ...TRIP,
      rescanned: false,
      queued: 0,
    })
    const created = vi.spyOn(api, 'createTrip')
    open({ trip: TRIP, prefill: PREFILL })

    expect(screen.getByRole('dialog', { name: 'Edit trip' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Japan spring')
    expect(chip('Dublin')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(created).not.toHaveBeenCalled()
    expect(updated).toHaveBeenCalledWith(7, {
      name: 'Japan spring',
      start_date: '2027-04-02',
      end_date: '2027-04-14',
      strict_dates: false,
      flex_before: 2,
      flex_after: 2,
      legs: [
        { country: 'JP', city: 'Tokyo', start_date: '2027-04-02', end_date: '2027-04-07' },
        { country: 'KR', city: null, start_date: null, end_date: null },
      ],
    })
  })
})
