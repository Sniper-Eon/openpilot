package com.garan.tesnav.vision

import kotlin.math.*

internal data class VehicleBox(val x1: Double, val y1: Double, val x2: Double, val y2: Double, val confidence: Double) {
    fun iou(other: VehicleBox): Double {
        val overlap = max(0.0, min(x2, other.x2) - max(x1, other.x1)) * max(0.0, min(y2, other.y2) - max(y1, other.y1))
        val union = (x2 - x1) * (y2 - y1) + (other.x2 - other.x1) * (other.y2 - other.y1) - overlap
        return if (union > 0) overlap / union else 0.0
    }
}

internal object SideVehicleGeometry {
    fun inside(polygon: List<List<Double>>, x: Double, y: Double): Boolean {
        if (polygon.size < 3) return false
        var inside = false
        var previous = polygon.last()
        for (point in polygon) {
            if ((point[1] > y) != (previous[1] > y) &&
                x < (previous[0] - point[0]) * (y - point[1]) / (previous[1] - point[1]) + point[0]) inside = !inside
            previous = point
        }
        return inside
    }

    // Matrix is built by C3 from the actual camera, height and live calibration.
    fun distance(box: VehicleBox, inverse: List<Double>?, width: Int, height: Int): Double? {
        if (inverse?.size != 9 || inverse.any { !it.isFinite() }) return null
        if (box.x1 <= 1 || box.x2 >= width - 1 || box.y2 >= height - 2) return null
        fun project(v: Double): Double? {
            val u = (box.x1 + box.x2) / 2
            val z = inverse[6] * u + inverse[7] * v + inverse[8]
            if (abs(z) < 1e-9) return null
            val x = (inverse[0] * u + inverse[1] * v + inverse[2]) / z
            return x.takeIf { it.isFinite() && it in 2.0..80.0 }
        }
        val x = project(box.y2) ?: return null
        val low = project(box.y2 - 2) ?: return null
        val high = project(box.y2 + 2) ?: return null
        return x.takeIf { abs(low - high) <= max(2.0, x * .20) }
    }

    fun decode(output: Array<FloatArray>, width: Int, height: Int, size: Int = 320): List<VehicleBox> {
        require(output.size == 5 && output.all { it.size == output[0].size })
        val scale = min(size.toDouble() / width, size.toDouble() / height)
        val dx = ((size - (width * scale).roundToInt()) / 2).toDouble()
        val dy = ((size - (height * scale).roundToInt()) / 2).toDouble()
        val candidates = output[0].indices.mapNotNull { i ->
            val confidence = output[4][i].toDouble()
            if (!confidence.isFinite() || confidence < .30) return@mapNotNull null
            val x = output[0][i].toDouble(); val y = output[1][i].toDouble()
            val w = output[2][i].toDouble(); val h = output[3][i].toDouble()
            if (listOf(x, y, w, h).any { !it.isFinite() } || w <= 0 || h <= 0) return@mapNotNull null
            val box = VehicleBox(((x - w / 2 - dx) / scale).coerceIn(0.0, width.toDouble()),
                ((y - h / 2 - dy) / scale).coerceIn(0.0, height.toDouble()),
                ((x + w / 2 - dx) / scale).coerceIn(0.0, width.toDouble()),
                ((y + h / 2 - dy) / scale).coerceIn(0.0, height.toDouble()), confidence)
            if (box.x2 - box.x1 < 4 || box.y2 - box.y1 < 4) null else box
        }.sortedByDescending { it.confidence }
        val keep = mutableListOf<VehicleBox>()
        for (box in candidates) if (keep.none { it.iou(box) > .45 }) keep.add(box)
        // Quarantine the scene-sized false positives found in the old training
        // labels. Preserve NMS and the existing 64-proposal limit for other boxes.
        return keep.take(64).filterNot { (it.x2 - it.x1) > width * .8 && (it.y2 - it.y1) > height * .8 }
    }
}

internal data class SideDetection(val box: VehicleBox, val side: String, val distance: Double?)
internal data class SideObservation(val track_id: Int, val distance_m: Double?, val relative_speed_mps: Double?,
    val absolute_speed_mps: Double?, val hits: Int, val confidence: Double)

internal class SideVehicleTracker {
    private data class Track(val id: Int, val side: String, var box: VehicleBox, var capture: Long,
        var hits: Int = 1, val history: MutableList<Pair<Long, Double>> = mutableListOf(),
        val motionHistory: MutableList<Pair<Long, Double>> = mutableListOf())
    private val tracks = mutableListOf<Track>()
    private var nextId = 1
    private var lastCapture = -1L
    private var lastEgoSpeed: Double? = null
    private var egoPosition = 0.0

    fun update(detections: List<SideDetection>, capture: Long, egoSpeed: Double?): Map<String, SideObservation?> {
        if (capture <= lastCapture) return mapOf("left" to null, "right" to null)
        if (lastCapture > 0 && capture - lastCapture > 800_000_000) tracks.clear()
        val currentEgo = egoSpeed?.takeIf { it.isFinite() }
        val previousEgo = lastEgoSpeed
        if (lastCapture > 0 && capture - lastCapture <= 800_000_000 &&
            previousEgo != null && currentEgo != null) {
            // Integrate over capture timestamps, not arrival/inference time. Fitting
            // distance + ego displacement uses the same window for both motions.
            egoPosition += (previousEgo + currentEgo) * .5 * ((capture - lastCapture) / 1e9)
        } else {
            egoPosition = 0.0
            tracks.forEach { it.motionHistory.clear() }
        }
        lastEgoSpeed = currentEgo
        lastCapture = capture
        tracks.removeAll { capture - it.capture > 600_000_000 }
        val used = mutableSetOf<Int>()
        val observed = mutableListOf<Track>()
        for (d in detections.sortedByDescending { it.box.confidence }) {
            val track = tracks.filter { it.id !in used && it.side == d.side && it.box.iou(d.box) >= .15 }
                .maxByOrNull { it.box.iou(d.box) }
            val active = if (track != null) {
                if (d.distance != null && track.history.isNotEmpty() &&
                    abs(d.distance - track.history.last().second) > 4.0) {
                    track.history.clear(); track.motionHistory.clear(); track.hits = 0
                }
                track.box = d.box; track.capture = capture; track.hits++; track
            } else Track(nextId++, d.side, d.box, capture).also { tracks.add(it) }
            if (d.distance != null && d.distance.isFinite()) {
                active.history.add(capture to d.distance)
                if (currentEgo != null) active.motionHistory.add(capture to (d.distance + egoPosition))
                else active.motionHistory.clear()
            } else {
                active.history.clear(); active.motionHistory.clear()
            }
            active.history.removeAll { capture - it.first > 2_500_000_000 }
            active.motionHistory.removeAll { capture - it.first > 2_500_000_000 }
            used.add(active.id); observed.add(active)
        }
        return listOf("left", "right").associateWith { side ->
            val tr = observed.filter { it.side == side && it.hits >= 3 }
                .minByOrNull { it.history.lastOrNull()?.second ?: Double.MAX_VALUE } ?: return@associateWith null
            val relative = slope(tr.history)?.takeIf { abs(it) <= 25 }
            val absolute = if (relative != null && currentEgo != null) slope(tr.motionHistory) else null
            SideObservation(tr.id, tr.history.lastOrNull()?.second, relative, absolute, tr.hits, tr.box.confidence)
        }
    }

    private fun slope(history: List<Pair<Long, Double>>): Double? {
        if (history.size < 5 || history.last().first - history.first().first < 800_000_000) return null
        val origin = history.first().first
        val x = history.map { (it.first - origin) / 1e9 }; val y = history.map { it.second }
        val mx = x.average(); val my = y.average()
        val denominator = x.sumOf { (it - mx).pow(2) }
        if (denominator < 1e-6) return null
        val slope = x.indices.sumOf { (x[it] - mx) * (y[it] - my) } / denominator
        val rmse = sqrt(x.indices.sumOf { (y[it] - my - slope * (x[it] - mx)).pow(2) } / x.size)
        return slope.takeIf { it.isFinite() && rmse <= .8 }
    }
}
