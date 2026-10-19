interface Props {
  score: number
}

/** Ten dots, one filled per tenth of the score. */
export function ScoreBar({ score }: Props) {
  const clamped = Math.max(0, Math.min(score, 1))
  const filled = Math.round(clamped * 10)
  return (
    <div className="score">
      <span
        className="dots"
        role="meter"
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={score.toFixed(2)}
        aria-label="match score"
      >
        {Array.from({ length: 10 }, (_, i) => (
          <i key={i} className={i < filled ? 'on' : undefined} />
        ))}
      </span>
      <span data-testid="score-value">{score.toFixed(2)}</span>
    </div>
  )
}
