import type { Status } from '../lib/types'
import { percent } from '../lib/format'

interface Props {
  status: Status
}

/** Partial coverage is reported honestly. A half-filled index and a quiet
 *  weekend look identical unless the app says which one it is. */
export function IndexProgress({ status }: Props) {
  const complete = status.coverage >= 1
  const queued = Object.values(status.queue).reduce((sum, kind) => sum + kind.total, 0)

  if (complete && !status.reindexing && status.degraded.length === 0) {
    return null
  }

  return (
    <>
      {!complete && (
        <div className="progress" data-testid="index-progress">
          <div className="progress-inner">
            <strong>
              {status.reindexing
                ? `Re-indexing for ${status.home.label}`
                : 'Building the index'}
            </strong>
            <span>
              {percent(status.coverage)} of the next {status.horizon_days} days
              {queued > 0 && ` · ${queued} task${queued === 1 ? '' : 's'} queued`}
            </span>
            <span className="bar">
              <i style={{ width: percent(status.coverage) }} />
            </span>
            <span>Results so far are real, just incomplete.</span>
          </div>
        </div>
      )}

      {status.degraded.length > 0 && (
        <div className="wrap notes">
          {status.degraded.map((problem) => (
            <div className="note" key={problem}>
              {problem}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
