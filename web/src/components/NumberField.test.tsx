import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { NumberField } from './NumberField'

function Field({ onChange }: { onChange: (value: number) => void }) {
  const [value, setValue] = useState(250)
  return (
    <>
      <label htmlFor="km">km</label>
      <NumberField
        id="km"
        min={25}
        max={3000}
        value={value}
        onChange={(next) => {
          setValue(next)
          onChange(next)
        }}
      />
    </>
  )
}

const field = () => screen.getByLabelText('km')

describe('NumberField', () => {
  it('can be cleared below its floor and retyped', async () => {
    const changed = vi.fn()
    render(<Field onChange={changed} />)

    await userEvent.type(field(), '{Backspace}{Backspace}{Backspace}500')

    expect(field()).toHaveValue(500)
    expect(changed.mock.calls).toEqual([[25], [50], [500]])
  })

  it('goes back to the last good value when left below its floor', async () => {
    const changed = vi.fn()
    render(<Field onChange={changed} />)

    await userEvent.clear(field())
    await userEvent.type(field(), '2')
    await userEvent.tab()

    expect(field()).toHaveValue(250)
    expect(changed).not.toHaveBeenCalled()
  })

  it('clamps a value over its ceiling', async () => {
    const changed = vi.fn()
    render(<Field onChange={changed} />)

    await userEvent.type(field(), '00')

    expect(field()).toHaveValue(3000)
    expect(changed).toHaveBeenLastCalledWith(3000)
  })
})
