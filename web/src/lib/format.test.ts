import { describe, expect, it } from 'vitest'
import {
  dateLabel,
  dateSpan,
  dayNumber,
  isWeekend,
  monthYear,
  placeParts,
  weekdayShort,
} from './format'

describe('dates', () => {
  it('labels a date by weekday, day and month', () => {
    expect(dateLabel('2027-04-03')).toBe('Sat 03 Apr')
  })

  it('keeps the leading zero on the day', () => {
    expect(dayNumber('2026-11-06')).toBe('06')
  })

  it('names the month and year', () => {
    expect(monthYear('2026-11-06')).toBe('Nov 2026')
  })

  it('counts Friday and Saturday as the weekend, and not Sunday', () => {
    expect(weekdayShort('2026-09-11')).toBe('Fri')
    expect(isWeekend('2026-09-11')).toBe(true)
    expect(isWeekend('2026-09-12')).toBe(true)
    expect(isWeekend('2026-09-13')).toBe(false)
  })
})

describe('dateSpan', () => {
  it('names the month once when both ends share it', () => {
    expect(dateSpan('2027-04-02', '2027-04-14')).toBe('02 — 14 Apr 2027')
  })

  it('names both months when the span crosses one', () => {
    expect(dateSpan('2027-02-28', '2027-03-03')).toBe('28 Feb — 03 Mar 2027')
  })

  it('names both years when the span crosses one', () => {
    expect(dateSpan('2026-12-28', '2027-01-03')).toBe('28 Dec 2026 — 03 Jan 2027')
  })

  it('collapses a single day to one date', () => {
    expect(dateSpan('2027-04-03', '2027-04-03')).toBe('03 Apr 2027')
  })

  it('can leave the year off', () => {
    expect(dateSpan('2027-04-02', '2027-04-07', { year: false })).toBe('02 — 07 Apr')
  })
})

describe('placeParts', () => {
  const place = { venue: 'The Fillmore', city: 'Fairview', region: 'KS', country: 'US' }

  it('leads with the town and puts the venue under it', () => {
    expect(placeParts(place)).toEqual({ title: 'Fairview, KS', sub: 'The Fillmore' })
  })

  it('falls back to the country code when there is no region', () => {
    const tokyo = { venue: 'Budokan', city: 'Tokyo', region: null, country: 'JP' }
    expect(placeParts(tokyo).title).toBe('Tokyo, JP')
    expect(placeParts(tokyo, { country: false }).title).toBe('Tokyo')
  })

  it('leads with the venue when there is no city', () => {
    const festival = { venue: 'Primavera Sound', city: null, region: null, country: 'ES' }
    expect(placeParts(festival)).toEqual({ title: 'Primavera Sound', sub: 'ES' })
  })

  it('says the venue is still to come when there is nothing at all', () => {
    const blank = { venue: null, city: null, region: null, country: null }
    expect(placeParts(blank)).toEqual({ title: 'venue to be announced', sub: null })
  })
})
