package com.garan.tesnav.normalization

import com.garan.tesnav.export.CanonicalJson
import com.garan.tesnav.export.NavAssistV2Mapper
import com.garan.tesnav.model.LaneAction
import com.garan.tesnav.model.LaneState
import com.garan.tesnav.model.NavigationState
import org.junit.Assert.*
import org.junit.Test

/** Compatibility cases at the SDK-observation -> model -> wire boundary. */
class AmapLaneNormalizerTest {
    @Test fun legacyPaddingStopsBeforeUnsigned255EvenWhenSdkReportsMoreLanes() {
        val lanes = AmapLaneNormalizer.legacy(
            listOf(observation(8)), byteArrayOf(0, 1, -1, 3), byteArrayOf(0, 1, 3, 3),
        )
        assertEquals(listOf(0, 1), lanes.map { it.index })
        assertEquals(listOf(0, 1), lanes.map { it.rawLaneType })
        assertTrue(AmapLaneNormalizer.legacy(null, byteArrayOf(-1, 1), null).isEmpty())
    }

    @Test fun legacyFixedWidthArraysDoNotCreatePhantomLanes() {
        val infos = List(3) { observation(3) }
        val lanes = AmapLaneNormalizer.legacy(
            infos, byteArrayOf(11, 1, 3, 15, 15, 15, 15, 15),
            byteArrayOf(1, 1, 15, 15, 15, 15, 15, 15),
        )
        assertEquals(listOf(0, 1, 2), lanes.map { it.index })
        assertEquals(listOf(11, 1, 3), lanes.map { it.rawLaneType })
        assertEquals(3, AmapLaneNormalizer.legacy(
            List(3) { observation(0) }, byteArrayOf(11, 1, 3, 15, 15, 15, 15, 15), null,
        ).size)
        assertEquals(3, AmapLaneNormalizer.legacy(
            List(3) { observation(8) }, byteArrayOf(11, 1, 3, 15, 15, 15, 15, 15), null,
        ).size)
        val fourLanes = AmapLaneNormalizer.legacy(
            List(4) { observation(4) }, byteArrayOf(1, 0, 0, 3, 15, 15, 15, 15),
            byteArrayOf(1, 0, 0, 3, 15, 15, 15, 15),
        )
        assertEquals(listOf(0, 1, 2, 3), fourLanes.map { it.index })
    }

    @Test fun oneLegacyEntryWithZeroDeclaredCountDoesNotUseEightBytePaddingAsLaneCount() {
        val lanes = AmapLaneNormalizer.legacy(
            listOf(observation(0)), byteArrayOf(2, 15, 15, 15, 15, 15, 15, 15),
            byteArrayOf(0, 15, 15, 15, 15, 15, 15, 15),
        )
        assertEquals(1, lanes.size)
        assertEquals(2, lanes.single().rawLaneType)
    }

    @Test fun legacyTypeCharactersTakePrecedenceOverParallelByteArrays() {
        val lane = AmapLaneNormalizer.legacy(
            listOf(observation(1, "21")), byteArrayOf(3), byteArrayOf(3),
        ).single()
        assertEquals(2, lane.rawLaneType)
        assertEquals(listOf(LaneAction.STRAIGHT, LaneAction.LEFT), lane.allowedActions)
        assertEquals(1, lane.rawRecommendedLaneType)
        assertEquals(listOf(LaneAction.LEFT), lane.recommendedActions)
    }

    @Test fun legacyInvalidCharactersFallBackToUnsignedByteValues() {
        val lane = AmapLaneNormalizer.legacy(
            listOf(observation(1, "?z", listOf(1))), byteArrayOf(-128), byteArrayOf(3),
        ).single()
        assertEquals(128, lane.rawLaneType)
        assertEquals(listOf(LaneAction.UNKNOWN), lane.allowedActions)
        assertEquals(listOf(LaneAction.RIGHT), lane.recommendedActions)
    }

    @Test fun legacyEmptyBackgroundUsesFirstSdkCountAndPerEntryFallback() {
        val lanes = AmapLaneNormalizer.legacy(
            listOf(observation(3, background = listOf(2))), byteArrayOf(), byteArrayOf(1),
        )
        assertEquals(listOf(2, -1, -1), lanes.map { it.rawLaneType })
        assertTrue(lanes[0].recommended)
        assertFalse(lanes[1].recommended)
        assertNull(lanes[2].rawRecommendedLaneType)
    }

    @Test fun legacyFIsRouteAvoidanceAndSuppressesByteRecommendation() {
        for (types in listOf("0F", "0f")) {
            val lane = AmapLaneNormalizer.legacy(
                listOf(observation(1, types)), byteArrayOf(0), byteArrayOf(1),
            ).single()
            assertTrue(lane.prohibited)
            assertFalse(lane.recommended)
            assertNull(lane.rawRecommendedLaneType)
            assertTrue(lane.recommendedActions.isEmpty())
        }
    }

    @Test fun legacyByteSentinelsAreNotRecommendationsOrImplicitAvoidance() {
        val lanes = AmapLaneNormalizer.legacy(null, byteArrayOf(0, 0, 0), byteArrayOf(15, 22, -1))
        assertEquals(3, lanes.size)
        assertTrue(lanes.all { !it.recommended && !it.prohibited && it.rawRecommendedLaneType == null })
    }

    @Test fun modernCountIsAuthoritativeAndMissingEntriesStayUnknown() {
        val lanes = AmapLaneNormalizer.modern(3, intArrayOf(1), intArrayOf(1))
        assertEquals(listOf(1, -1, -1), lanes.map { it.rawLaneType })
        assertEquals(listOf(true, false, false), lanes.map { it.recommended })
        assertEquals(listOf(LaneAction.UNKNOWN), lanes[2].allowedActions)
        assertEquals(1, AmapLaneNormalizer.modern(1, intArrayOf(0, 1), intArrayOf(0, 1)).size)
    }

    @Test fun modernOnly255MarksRouteAvoidance() {
        val lanes = AmapLaneNormalizer.modern(3, intArrayOf(0, 0, 0), intArrayOf(15, 22, 255))
        assertEquals(listOf(false, false, true), lanes.map { it.prohibited })
        assertTrue(lanes.all { !it.recommended && it.recommendedActions.isEmpty() })
    }

    @Test fun emptyAndNegativeCountsDoNotInventLanes() {
        assertTrue(AmapLaneNormalizer.modern(-1, intArrayOf(0), intArrayOf(0)).isEmpty())
        assertTrue(AmapLaneNormalizer.modern(0, null, null).isEmpty())
        assertTrue(AmapLaneNormalizer.legacy(null, null, null).isEmpty())
        assertTrue(AmapLaneNormalizer.legacy(listOf(observation(-1)), null, null).isEmpty())
    }

    @Test fun unknownNonSentinelRecommendationRetainsExistingUnknownAction() {
        val modern = AmapLaneNormalizer.modern(1, intArrayOf(99), intArrayOf(99)).single()
        val legacy = AmapLaneNormalizer.legacy(null, byteArrayOf(99), byteArrayOf(99)).single()
        for (lane in listOf(modern, legacy)) {
            assertTrue(lane.recommended)
            assertEquals(listOf(LaneAction.UNKNOWN), lane.recommendedActions)
            assertEquals(99, lane.rawRecommendedLaneType)
        }
    }

    @Test fun displayAndWireUTurnMappingsRemainDistinctAcrossCallbackFormats() {
        val modern = AmapLaneNormalizer.modern(1, intArrayOf(5), intArrayOf(5))
        val legacy = AmapLaneNormalizer.legacy(null, byteArrayOf(5), byteArrayOf(5))
        assertEquals(listOf(LaneAction.U_TURN), modern.single().recommendedActions)
        assertEquals(listOf(LaneAction.LEFT_U_TURN), legacy.single().recommendedActions)
        assertEquals(wireLanes(legacy), wireLanes(modern))
        assertEquals(
            "{\"items\":[{\"allowedActions\":[\"LEFT_U_TURN\"],\"index\":0,\"recommended\":true," +
                "\"recommendedActions\":[\"LEFT_U_TURN\"],\"routeAvoid\":false}],\"observedAtMs\":1000,\"totalCount\":1}",
            wireLanes(modern),
        )
    }

    @Test fun routeAvoidanceAndRawWireMappingMatchCanonicalContract() {
        val modern = AmapLaneNormalizer.modern(2, intArrayOf(17, 13), intArrayOf(255, 13))
        val legacy = AmapLaneNormalizer.legacy(
            listOf(observation(2), observation(2, "DD")), byteArrayOf(17, 13), byteArrayOf(-1, 13),
        )
        assertEquals(listOf(LaneAction.UNKNOWN), modern[1].recommendedActions)
        assertEquals(listOf(LaneAction.STRAIGHT), legacy[1].recommendedActions)
        assertEquals(
            "{\"items\":[{\"allowedActions\":[\"RIGHT\",\"LEFT_U_TURN\"],\"index\":0,\"recommended\":false," +
                "\"recommendedActions\":[],\"routeAvoid\":true},{\"allowedActions\":[\"STRAIGHT\"],\"index\":1," +
                "\"recommended\":true,\"recommendedActions\":[\"STRAIGHT\"],\"routeAvoid\":false}],\"observedAtMs\":1000,\"totalCount\":2}",
            wireLanes(modern),
        )
        assertFalse(legacy[0].prohibited) // Legacy byte 255 is intentionally different from modern 255.
    }

    @Test fun wireLaneLimitStaysAtTransportBoundary() {
        val lanes = AmapLaneNormalizer.modern(20, IntArray(20), IntArray(20))
        assertEquals(20, lanes.size)
        val snapshot = NavAssistV2Mapper.snapshot(
            NavigationState(lanes = lanes, lanesObservedAtMs = 1000, acceptedPathId = 42,
                guidancePathId = 42, lanesPathId = 42), "fixture", 1, 1000, 1200,
        )
        assertEquals((0..15).toList(), snapshot.lanes!!.items.map { it.index })
        assertFalse(snapshot.routeActive)
        assertEquals(0L, snapshot.maneuverEventId)
    }

    private fun observation(count: Int, types: String? = null, background: List<Int>? = null) =
        LegacyLaneObservation(count, types?.toList(), background)

    private fun wireLanes(lanes: List<LaneState>): String = CanonicalJson.encode(
        NavAssistV2Mapper.snapshot(
            NavigationState(lanes = lanes, lanesObservedAtMs = 1000, acceptedPathId = 42,
                guidancePathId = 42, lanesPathId = 42), "fixture", 1, 1000, 1200,
        ).lanes!!,
    )
}
