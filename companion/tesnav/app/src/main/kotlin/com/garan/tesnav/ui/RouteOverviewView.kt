package com.garan.tesnav.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.view.View
import com.garan.tesnav.model.GeoPoint
import kotlin.math.cos

/** Draws the complete route geometry without a map background. */
class RouteOverviewView(context: Context) : View(context) {
    private val density = resources.displayMetrics.density
    private val routePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(0, 120, 255)
        style = Paint.Style.STROKE
        strokeWidth = 4f * density
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(84, 110, 122)
        textSize = 14f * density
    }
    private var points: List<GeoPoint> = emptyList()

    fun setRoute(points: List<GeoPoint>) {
        this.points = points
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (points.size < 2) {
            val label = "暂无路线"
            val x = (width - labelPaint.measureText(label)) / 2f
            val y = height / 2f - (labelPaint.ascent() + labelPaint.descent()) / 2f
            canvas.drawText(label, x, y, labelPaint)
            return
        }

        val meanLatitude = points.sumOf(GeoPoint::latitude) / points.size
        val longitudeScale = cos(Math.toRadians(meanLatitude)).coerceAtLeast(0.01)
        val projected = points.map { point ->
            ProjectedPoint(point.longitude * longitudeScale, point.latitude)
        }
        val minX = projected.minOf(ProjectedPoint::x)
        val maxX = projected.maxOf(ProjectedPoint::x)
        val minY = projected.minOf(ProjectedPoint::y)
        val maxY = projected.maxOf(ProjectedPoint::y)
        val padding = 28f * density
        val availableWidth = (width - padding * 2f).coerceAtLeast(1f)
        val availableHeight = (height - padding * 2f).coerceAtLeast(1f)
        val spanX = (maxX - minX).coerceAtLeast(1e-9)
        val spanY = (maxY - minY).coerceAtLeast(1e-9)
        val scale = minOf(availableWidth / spanX, availableHeight / spanY)
        val drawnWidth = spanX * scale
        val drawnHeight = spanY * scale
        val offsetX = (width - drawnWidth) / 2f
        val offsetY = (height - drawnHeight) / 2f

        fun screen(point: ProjectedPoint): Pair<Float, Float> {
            val x = (offsetX + (point.x - minX) * scale).toFloat()
            val y = (offsetY + (maxY - point.y) * scale).toFloat()
            return x to y
        }

        val route = Path()
        projected.forEachIndexed { index, point ->
            val (x, y) = screen(point)
            if (index == 0) route.moveTo(x, y) else route.lineTo(x, y)
        }
        canvas.drawPath(route, routePaint)
    }

    private data class ProjectedPoint(val x: Double, val y: Double)
}
