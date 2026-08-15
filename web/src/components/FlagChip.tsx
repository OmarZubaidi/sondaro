interface Props {
  flag: string
}

/** Flags carry different weights: "major planning" is a real caveat, an
 *  estimated drive time is just a caveat about precision. */
function toneFor(flag: string): string {
  if (flag.startsWith('not on your itinerary') || flag.startsWith('major planning')) {
    return 'chip warn'
  }
  if (flag === 'outside your dates') return 'chip warn'
  if (flag === 'not in your library') return 'chip info'
  return 'chip'
}

export function FlagChip({ flag }: Props) {
  return <span className={toneFor(flag)}>{flag}</span>
}
