interface Props {
  score: number
}

export function ScoreBar({ score }: Props) {
  const pct = Math.round(Math.max(0, Math.min(score, 1)) * 100)
  return (
    <div className="score">
      <span data-testid="score-value">{score.toFixed(2)}</span>
      <div
        className="meter"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="match score"
      >
        <i style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
