package com.garan.tesnav.vision

import kotlin.math.*

internal data class GroundPoint(val forward: Double, val lateral: Double, val pixelSensitivity: Double = 0.0)
internal data class DualMatch(val wideIndex: Int, val narrowIndex: Int, val point: GroundPoint, val confidence: Double)

/** Associates two ground projections. It is NOT a stereo triangulation model. */
internal object DualGroundGeometry {
    fun project(box: VehicleBox, inverse: List<Double>?, width: Int, height: Int): GroundPoint? {
        if (width <= 0 || height <= 0 || inverse?.size != 9 || inverse.any { !it.isFinite() }) return null
        if (listOf(box.x1, box.y1, box.x2, box.y2, box.confidence).any { !it.isFinite() } ||
            box.x1 <= 1 || box.y1 < 0 || box.x2 >= width-1 || box.y2 >= height-2 ||
            box.x2 <= box.x1 || box.y2 <= box.y1 || box.confidence !in .3..1.0) return null
        fun at(v: Double): GroundPoint? {
            val u = (box.x1+box.x2)/2
            val z = inverse[6]*u+inverse[7]*v+inverse[8]
            if (abs(z) < 1e-9) return null
            val x = (inverse[0]*u+inverse[1]*v+inverse[2])/z
            val y = (inverse[3]*u+inverse[4]*v+inverse[5])/z
            return GroundPoint(x, y).takeIf { x.isFinite() && y.isFinite() && x in 2.0..80.0 && abs(y) <= 25 }
        }
        val p = at(box.y2) ?: return null
        val low = at(box.y2-2) ?: return null
        val high = at(box.y2+2) ?: return null
        return p.copy(pixelSensitivity=abs(low.forward-high.forward)/4).takeIf { abs(low.forward-high.forward) <= max(2.0, p.forward*.2) }
    }

    fun associate(wide: List<VehicleBox>, narrow: List<VehicleBox>, wi: List<Double>?, ni: List<Double>?,
                  ww: Int, wh: Int, nw: Int, nh: Int, skewMs: Double): List<DualMatch> {
        if (!skewMs.isFinite() || skewMs !in 0.0..20.0 || wide.size > 64 || narrow.size > 64) return emptyList()
        val wp = wide.map { project(it, wi, ww, wh) }; val np = narrow.map { project(it, ni, nw, nh) }
        fun cost(i: Int, j: Int): Double? {
            val a=wp[i] ?: return null; val b=np[j] ?: return null
            val forwardScale=max(1.0, min(a.forward,b.forward)*.08)
            val dx=abs(a.forward-b.forward)/forwardScale; val dy=abs(a.lateral-b.lateral)/.6
            return (dx+dy).takeIf { dx <= 1 && dy <= 1 }
        }
        fun unique(candidates: List<Pair<Int,Double>>): Int? {
            val sorted=candidates.sortedBy { it.second }
            if (sorted.isEmpty() || (sorted.size>1 && sorted[1].second-sorted[0].second < .35)) return null
            return sorted[0].first
        }
        val wb=wide.indices.map { i -> unique(narrow.indices.mapNotNull { j -> cost(i,j)?.let { j to it } }) }
        val nb=narrow.indices.map { j -> unique(wide.indices.mapNotNull { i -> cost(i,j)?.let { i to it } }) }
        return wb.mapIndexedNotNull { i,j ->
            if (j == null || nb[j] != i) null else {
                val a=wp[i]!!; val b=np[j]!!
                // Use the less pixel-sensitive camera, usually the narrow lens.
                // Averaging correlated calibration errors would imply precision
                // we have not measured. The other view confirms association only.
                val estimate=if(b.pixelSensitivity<=a.pixelSensitivity)b else a
                DualMatch(i,j,estimate,min(wide[i].confidence,narrow[j].confidence))
            }
        }
    }
}

internal data class DualGroundObservation(val track_id: Int, val wide_index: Int, val narrow_index: Int,
    val distance_m: Double, val relative_speed_mps: Double?, val absolute_speed_mps: Double?,
    val confidence: Double, val distance_source: String = "dual_ground_estimate",
    val control_eligible: Boolean = false, val clearance_authorized: Boolean = false)

internal class DualGroundTracker(private val source: String = "dual_ground_estimate") {
    private data class Track(val id: Int, var box: VehicleBox, var capture: Long, var point: GroundPoint,
        var hits: Int = 1, val history: MutableList<Pair<Long,Double>> = mutableListOf(),
        val motion: MutableList<Pair<Long,Double>> = mutableListOf())
    private val tracks=mutableListOf<Track>()
    private var next=1; private var previous=-1L; private var ego: Double?=null; private var position=0.0
    fun update(matches: List<DualMatch>, wide: List<VehicleBox>, capture: Long, speed: Double?): List<DualGroundObservation> {
        if (capture <= previous) return emptyList()
        val current=speed?.takeIf { it.isFinite() && it in 0.0..70.0 }
        if (previous>=0 && capture-previous<=600_000_000 && current!=null && ego!=null)
            position+=(current+ego!!)*.5*((capture-previous)/1e9)
        else { position=0.0; tracks.forEach { it.motion.clear() } }
        if (previous>=0 && capture-previous>600_000_000) tracks.clear()
        previous=capture;ego=current
        tracks.removeAll { capture-it.capture>600_000_000 }
        val used=mutableSetOf<Int>();val observed=mutableListOf<Pair<Track,DualMatch>>()
        for (match in matches) {
            if (match.wideIndex !in wide.indices) continue
            val box=wide[match.wideIndex]
            val candidates=tracks.filter { it.id !in used && it.box.iou(box)>=.2 &&
                abs(it.point.forward-match.point.forward)<=4 && abs(it.point.lateral-match.point.lateral)<=.75 }
                .sortedByDescending { it.box.iou(box) }
            val track=if(candidates.size>1 && candidates[0].box.iou(box)-candidates[1].box.iou(box)<.1) null else candidates.firstOrNull()
            val active=track?.also { it.box=box;it.point=match.point;it.capture=capture;it.hits++ }
                ?: Track(next++,box,capture,match.point).also { tracks.add(it) }
            active.history.add(capture to match.point.forward)
            if(current!=null) active.motion.add(capture to (match.point.forward+position)) else active.motion.clear()
            active.history.removeAll { capture-it.first>2_500_000_000 };active.motion.removeAll { capture-it.first>2_500_000_000 }
            used.add(active.id);observed.add(active to match)
        }
        return observed.filter { it.first.hits>=3 }.take(16).map { (track,match) ->
            val relative=slope(track.history)?.takeIf { abs(it)<=25 }
            val absolute=if(relative!=null && current!=null) slope(track.motion)?.takeIf { abs(it)<=70 } else null
            DualGroundObservation(track.id,match.wideIndex,match.narrowIndex,match.point.forward,relative,absolute,match.confidence,source)
        }
    }
    private fun slope(history: List<Pair<Long,Double>>): Double? {
        if(history.size<5 || history.last().first-history.first().first<800_000_000) return null
        val origin=history.first().first;val x=history.map { (it.first-origin)/1e9 };val y=history.map { it.second }
        val mx=x.average();val my=y.average();val den=x.sumOf { (it-mx).pow(2) }
        if(den<1e-6) return null
        val v=x.indices.sumOf { (x[it]-mx)*(y[it]-my) }/den
        val rmse=sqrt(x.indices.sumOf { (y[it]-my-v*(x[it]-mx)).pow(2) }/x.size)
        return v.takeIf { it.isFinite() && rmse<=.8 }
    }
}
