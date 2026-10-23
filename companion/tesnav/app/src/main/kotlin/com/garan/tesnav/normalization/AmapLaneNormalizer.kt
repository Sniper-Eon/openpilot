package com.garan.tesnav.normalization

import com.garan.tesnav.model.LaneState
import com.garan.tesnav.util.NavigationMappers

/** Primitive snapshot of one legacy SDK lane entry; no SDK object escapes the adapter. */
data class LegacyLaneObservation(
    val laneCount: Int,
    val typeIds: List<Char>?,
    val backgroundLane: List<Int>?,
)

/**
 * Stateless normalization of the two AMap callback formats.
 *
 * Intentionally preserves the existing display/wire mapping differences and source precedence.
 * Route avoidance is a navigation hint, never a physical crossing permission or prohibition.
 * Timestamps, route validity and callback diagnostics belong to the caller.
 */
object AmapLaneNormalizer {
    fun legacy(
        laneInfos: List<LegacyLaneObservation>?,
        background: ByteArray?,
        recommended: ByteArray?,
    ): List<LaneState> {
        val raw = background ?: byteArrayOf()
        val front = recommended ?: byteArrayOf()
        val firstPadding = raw.indexOfFirst { it.toInt().and(0xff) == 0xff }
        val rawCount = when {
            firstPadding >= 0 -> firstPadding
            raw.isNotEmpty() -> raw.size
            else -> 0
        }
        val sdkCount = laneInfos?.takeIf { it.isNotEmpty() }?.let { infos ->
            val declared = infos.first().laneCount.takeIf { it > 0 }
            if (infos.size > 1) minOf(declared ?: infos.size, infos.size)
            else declared ?: infos.size.takeIf { raw.isNotEmpty() }
        }
        val count = when {
            sdkCount != null && raw.isNotEmpty() -> minOf(sdkCount, rawCount)
            sdkCount != null -> sdkCount
            else -> rawCount
        }
        return (0 until count).map { index ->
            val info = laneInfos?.getOrNull(index)
            val legacyTypes = info?.typeIds
            val laneRaw = legacyTypes?.getOrNull(0)?.digitToIntOrNull(16)
                ?: raw.getOrNull(index)?.toInt()?.and(0xff)
                ?: info?.backgroundLane?.firstOrNull() ?: -1
            val legacyRecommended = legacyTypes?.getOrNull(1)
            val recommendedRaw = legacyRecommended?.digitToIntOrNull(16)
                ?: front.getOrNull(index)?.toInt()?.and(0xff)
            val prohibited = legacyRecommended?.uppercaseChar() == 'F'
            val recommendedActions = recommendedRaw
                ?.takeUnless { it in setOf(15, 22, 255) }
                ?.let(NavigationMappers::navAssistV2LaneActions)
                .orEmpty()
            LaneState(
                index = index,
                allowedActions = NavigationMappers.laneActions(laneRaw),
                recommended = !prohibited && recommendedActions.isNotEmpty(),
                rawLaneType = laneRaw,
                recommendedActions = recommendedActions,
                rawRecommendedLaneType = recommendedRaw?.takeUnless { it in setOf(15, 22, 255) },
                prohibited = prohibited,
            )
        }
    }

    fun modern(laneCount: Int, background: IntArray?, recommended: IntArray?): List<LaneState> {
        val count = laneCount.coerceAtLeast(0)
        val recommendedActions = NavigationMappers.laneRecommendedActions(count, recommended)
        return (0 until count).map { index ->
            val raw = background?.getOrNull(index) ?: -1
            LaneState(
                index = index,
                allowedActions = NavigationMappers.laneActions(raw),
                recommended = recommendedActions[index].isNotEmpty(),
                rawLaneType = raw,
                recommendedActions = recommendedActions[index],
                rawRecommendedLaneType = recommended?.getOrNull(index)?.takeUnless { it in setOf(15, 22, 255) },
                prohibited = recommended?.getOrNull(index) == 255,
            )
        }
    }
}
