import { useState } from 'react'
import type { Trip } from '../lib/types'

export interface TripFields {
  name: string
  countries: string
  cities: string
  start_date: string
  end_date: string
  flex_before: number
  flex_after: number
  strict_dates: boolean
}

export function fieldsFromTrip(trip: Trip): TripFields {
  return {
    name: trip.name,
    countries: trip.countries.join(', '),
    cities: trip.cities.join(', '),
    start_date: trip.start_date,
    end_date: trip.end_date,
    flex_before: trip.flex_before,
    flex_after: trip.flex_after,
    strict_dates: trip.strict_dates,
  }
}

export function toPayload(fields: TripFields): Record<string, unknown> {
  const list = (value: string) =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)

  return {
    ...fields,
    countries: list(fields.countries).map((c) => c.toUpperCase()),
    cities: list(fields.cities),
  }
}

interface Props {
  initial: TripFields
  countries: { code: string; name: string }[]
  submitLabel: string
  busy?: boolean
  onSubmit: (fields: TripFields) => void
  onCancel?: () => void
}

/** Shared by "new trip" and "edit trip" so the two can't drift apart. */
export function TripForm({
  initial,
  countries,
  submitLabel,
  busy = false,
  onSubmit,
  onCancel,
}: Props) {
  const [fields, setFields] = useState<TripFields>(initial)
  const set = <K extends keyof TripFields>(key: K, value: TripFields[K]) =>
    setFields((current) => ({ ...current, [key]: value }))

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit(fields)
      }}
    >
      <div>
        <label htmlFor="trip-name">Name</label>
        <input
          id="trip-name"
          type="text"
          required
          value={fields.name}
          onChange={(e) => set('name', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="trip-countries">
          Countries, 2-letter codes. Trips can span several.
        </label>
        <input
          id="trip-countries"
          type="text"
          required
          placeholder="FR, ES"
          list="country-codes"
          value={fields.countries}
          onChange={(e) => set('countries', e.target.value)}
        />
        <datalist id="country-codes">
          {countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
        </datalist>
      </div>

      <div>
        <label htmlFor="trip-cities">
          Cities (optional). Name them per country as you book: a country with
          no city named stays wide open.
        </label>
        <input
          id="trip-cities"
          type="text"
          placeholder="Lyon, Barcelona"
          value={fields.cities}
          onChange={(e) => set('cities', e.target.value)}
        />
      </div>

      <div className="grid2">
        <div>
          <label htmlFor="trip-start">Start</label>
          <input
            id="trip-start"
            type="date"
            required
            value={fields.start_date}
            onChange={(e) => set('start_date', e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="trip-end">End</label>
          <input
            id="trip-end"
            type="date"
            required
            value={fields.end_date}
            onChange={(e) => set('end_date', e.target.value)}
          />
        </div>
      </div>

      <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          type="checkbox"
          checked={fields.strict_dates}
          onChange={(e) => set('strict_dates', e.target.checked)}
        />
        Strict dates, already booked
      </label>

      {!fields.strict_dates && (
        <div className="grid2">
          <div>
            <label htmlFor="flex-before">Days of slack before</label>
            <input
              id="flex-before"
              type="number"
              min={0}
              max={30}
              value={fields.flex_before}
              onChange={(e) => set('flex_before', Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="flex-after">Days of slack after</label>
            <input
              id="flex-after"
              type="number"
              min={0}
              max={30}
              value={fields.flex_after}
              onChange={(e) => set('flex_after', Number(e.target.value))}
            />
          </div>
        </div>
      )}

      <div className="row">
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'Saving…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}
