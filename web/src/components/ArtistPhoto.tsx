import { useState } from 'react'

interface Props {
  src: string | null | undefined
  className?: string
}

/** A photo that degrades to a plain ink tile.
 *
 *  Decorative, since the name is always beside it. The URL is a third party's,
 *  so it's fetched without a referrer, and a browser that can't reach it gets
 *  the tile rather than a broken image. */
export function ArtistPhoto({ src, className }: Props) {
  // keyed by URL, so a feed reload that brings a different photo tries again
  const [failed, setFailed] = useState<string | null>(null)

  return (
    <span className={`artist-photo${className ? ` ${className}` : ''}`} aria-hidden="true">
      {src && src !== failed && (
        <img
          src={src}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(src)}
        />
      )}
    </span>
  )
}
