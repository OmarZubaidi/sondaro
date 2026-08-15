interface Props {
  flag: string
}

/** Flags carry different weights: being in the wrong country is a real caveat,
 *  an estimated drive time is only a caveat about precision. */
function toneFor(flag: string): string {
  if (flag.startsWith('not on your itinerary')) return 'chip warn'
  if (flag === 'outside your dates') return 'chip warn'
  return 'chip'
}

export function FlagChip({ flag }: Props) {
  return <span className={toneFor(flag)}>{flag}</span>
}
