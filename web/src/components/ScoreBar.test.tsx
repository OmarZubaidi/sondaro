import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ScoreBar } from './ScoreBar'

const filled = () => document.querySelectorAll('.dots i.on').length

describe('ScoreBar', () => {
  it('fills one dot per tenth of the score, rounded', () => {
    render(<ScoreBar score={0.64} />)
    expect(document.querySelectorAll('.dots i')).toHaveLength(10)
    expect(filled()).toBe(6)
  })

  it('never fills more than ten', () => {
    render(<ScoreBar score={1.3} />)
    expect(filled()).toBe(10)
  })

  it('tells assistive tech the score the dots stand for', () => {
    render(<ScoreBar score={0.64} />)
    const meter = screen.getByRole('meter', { name: 'match score' })
    expect(meter).toHaveAttribute('aria-valuetext', '0.64')
  })
})
