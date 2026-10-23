package com.garan.tesnav.util

import com.garan.tesnav.model.GeoPoint
import kotlin.math.cos
import kotlin.math.hypot

object RouteGeometrySimplifier {
    data class Result(
        val points: List<GeoPoint>,
        val toleranceMeters: Double,
    )

    fun simplifyForViewport(
        points: List<GeoPoint>,
        viewportWidthPixels: Double,
        viewportHeightPixels: Double,
        paddingPixels: Double = 0.0,
        tolerancePixels: Double = 1.5,
    ): Result {
        if (points.size <= 2) return Result(points, 0.0)

        val meanLatitudeRadians = Math.toRadians(points.sumOf(GeoPoint::latitude) / points.size)
        val projected = points.map { point ->
            ProjectedPoint(
                x = EARTH_RADIUS_METERS * Math.toRadians(point.longitude) * cos(meanLatitudeRadians),
                y = EARTH_RADIUS_METERS * Math.toRadians(point.latitude),
            )
        }
        val spanX = (projected.maxOf(ProjectedPoint::x) - projected.minOf(ProjectedPoint::x)).coerceAtLeast(1e-9)
        val spanY = (projected.maxOf(ProjectedPoint::y) - projected.minOf(ProjectedPoint::y)).coerceAtLeast(1e-9)
        val availableWidth = (viewportWidthPixels - paddingPixels * 2.0).coerceAtLeast(1.0)
        val availableHeight = (viewportHeightPixels - paddingPixels * 2.0).coerceAtLeast(1.0)
        val pixelsPerMeter = minOf(availableWidth / spanX, availableHeight / spanY)
        val toleranceMeters = tolerancePixels / pixelsPerMeter

        val keep = BooleanArray(points.size)
        keep[0] = true
        keep[points.lastIndex] = true
        val ranges = ArrayDeque<Pair<Int, Int>>()
        ranges.addLast(0 to points.lastIndex)

        while (ranges.isNotEmpty()) {
            val (start, end) = ranges.removeLast()
            var farthestIndex = -1
            var farthestDistance = 0.0
            for (index in start + 1 until end) {
                val distance = perpendicularDistance(projected[index], projected[start], projected[end])
                if (distance > farthestDistance) {
                    farthestDistance = distance
                    farthestIndex = index
                }
            }
            if (farthestIndex >= 0 && farthestDistance > toleranceMeters) {
                keep[farthestIndex] = true
                ranges.addLast(start to farthestIndex)
                ranges.addLast(farthestIndex to end)
            }
        }
        return Result(points.filterIndexed { index, _ -> keep[index] }, toleranceMeters)
    }

    private fun perpendicularDistance(point: ProjectedPoint, start: ProjectedPoint, end: ProjectedPoint): Double {
        val deltaX = end.x - start.x
        val deltaY = end.y - start.y
        val lengthSquared = deltaX * deltaX + deltaY * deltaY
        if (lengthSquared == 0.0) return hypot(point.x - start.x, point.y - start.y)
        val position = ((point.x - start.x) * deltaX + (point.y - start.y) * deltaY) / lengthSquared
        val closestX = start.x + position.coerceIn(0.0, 1.0) * deltaX
        val closestY = start.y + position.coerceIn(0.0, 1.0) * deltaY
        return hypot(point.x - closestX, point.y - closestY)
    }

    private data class ProjectedPoint(val x: Double, val y: Double)

    private const val EARTH_RADIUS_METERS = 6_371_000.0
}
