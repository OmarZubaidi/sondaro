import { Suspense, lazy } from 'react'
import type { RouteMapProps } from './RouteMap'

const RouteMap = lazy(() => import('./RouteMap').then((module) => ({ default: module.RouteMap })))

/** The map, loaded on first use, so d3-geo and the drawing code stay out of
 *  the bundle every page pays for. */
export function LazyRouteMap(props: RouteMapProps) {
  if (props.stops.length === 0 && !props.nearby?.length && !props.loose?.length) return null
  return (
    <Suspense fallback={<div className="route-map" />}>
      <RouteMap {...props} />
    </Suspense>
  )
}
