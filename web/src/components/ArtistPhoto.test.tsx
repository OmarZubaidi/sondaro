import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ArtistPhoto } from './ArtistPhoto'

const photo = () => document.querySelector('.artist-photo img')

describe('ArtistPhoto', () => {
  it('loads the photo lazily and without a referrer', () => {
    render(<ArtistPhoto src="https://img.test/a.jpg" />)

    expect(photo()).toHaveAttribute('src', 'https://img.test/a.jpg')
    expect(photo()).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(photo()).toHaveAttribute('loading', 'lazy')
  })

  it('falls back to a plain tile when the photo won’t load', () => {
    render(<ArtistPhoto src="https://img.test/gone.jpg" />)

    fireEvent.error(photo()!)

    expect(photo()).toBeNull()
    expect(document.querySelector('.artist-photo')).toBeInTheDocument()
  })

  it('tries again when a different photo arrives', () => {
    const { rerender } = render(<ArtistPhoto src="https://img.test/gone.jpg" />)
    fireEvent.error(photo()!)

    rerender(<ArtistPhoto src="https://img.test/new.jpg" />)

    expect(photo()).toHaveAttribute('src', 'https://img.test/new.jpg')
  })

  it('is just the tile when there is no photo', () => {
    render(<ArtistPhoto src={null} />)

    expect(photo()).toBeNull()
    expect(document.querySelector('.artist-photo')).toBeInTheDocument()
  })
})
