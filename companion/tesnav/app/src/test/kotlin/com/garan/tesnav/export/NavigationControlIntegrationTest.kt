package com.garan.tesnav.export

import com.garan.tesnav.BuildConfig
import com.garan.tesnav.model.*
import java.io.File
import org.junit.Assert.*
import org.junit.Test

/** Outputs production-mapper packets for the offline C3 integration check. */
class NavigationControlIntegrationTest {
    @Test fun `SDK ramp and entrance links export directional packets without lane guidance`() {
        val packets = linkedMapOf<String, NavAssistV2Snapshot>()
        for (roadType in listOf(6, 8, 9, 10)) {
            for ((name, icon) in listOf("left" to 4, "right" to 5)) {
                val session = NavAssistV2Session(sessionId = "ramp-$roadType-$name")
                for (distance in listOf(1500, 50)) {
                    val state = NavigationState(navigationMode = NavigationMode.REALTIME,
                        navAssistControlAllowed = true, routePlanned = true, routeMatched = true,
                        acceptedPathId = 7, guidancePathId = 7,
                        currentStepIndex = 2, guidanceStepIndex = 2, routeRevision = 1,
                        latitude = 31.23, longitude = 121.47, accuracy = 2f, bearing = 90f, speedKph = 90f,
                        locationObservedAtMs = 10_000, guidanceObservedAtMs = 10_000,
                        currentRoadClass = 7, currentRoadType = 1,
                        maneuver = com.garan.tesnav.util.NavigationMappers.maneuver(icon, roadType),
                        nextTurnDistanceMeters = distance)
                    val packet = session.nextSnapshot(state, 10_000)
                    assertTrue(packet.routeActive)
                    assertEquals("${if (roadType == 9) "exit" else "ramp"}_$name", packet.guidance?.maneuver)
                    assertNull(packet.lanes)
                    packets["$roadType-$name-$distance"] = packet
                }
            }
        }
        File("build/navassist/ramp-integration.json").apply {
            parentFile.mkdirs()
            writeText(CanonicalJson.encode(packets), Charsets.UTF_8)
        }
    }

    @Test fun `SDK source gate exports directional events and cancellation for C3`() {
        val packets = linkedMapOf<String, NavAssistV2Snapshot>()
        for (direction in listOf(NavigationManeuver.TURN_LEFT, NavigationManeuver.TURN_RIGHT)) {
            val name = if (direction == NavigationManeuver.TURN_LEFT) "left" else "right"
            val gate = NavigationSourceGate(BuildConfig.NAV_ASSIST_SOURCE_BUDGET_MS,
                BuildConfig.NAV_ASSIST_PROGRESS_BUDGET_MS).apply { arm(100) }
            val session = NavAssistV2Session(sessionId = "integration-$name")
            val initial = NavigationState(navigationMode = NavigationMode.REALTIME,
                routePlanned = true, routeMatched = true, acceptedPathId = 7, guidancePathId = 7,
                currentStepIndex = 2, guidanceStepIndex = 2, routeRevision = 1,
                latitude = 31.23, longitude = 121.47, accuracy = 2f, bearing = 90f, speedKph = 36f,
                locationObservedAtMs = 10_000, guidanceObservedAtMs = 10_000,
                locationReceivedElapsedMs = 100, guidanceReceivedElapsedMs = 100,
                maneuver = direction, nextTurnDistanceMeters = 400)
            fun emit(suffix: String, state: NavigationState, elapsed: Long, wall: Long) =
                session.nextSnapshot(gate.prepare(state, elapsed, wall), wall).also { packets["$name-$suffix"] = it }
            val far = emit("far", initial, 100, 10_000)
            val near = emit("near", initial.copy(nextTurnDistanceMeters = 50,
                locationObservedAtMs = 12_000, guidanceObservedAtMs = 12_000,
                locationReceivedElapsedMs = 2_100, guidanceReceivedElapsedMs = 2_100), 2_100, 12_000)
            assertTrue(far.routeActive && near.routeActive)
            assertEquals(far.maneuverEventId, near.maneuverEventId)
            assertFalse(emit("lost", initial, 5_101, 15_001).routeActive)
            val fresh = initial.copy(locationObservedAtMs = 16_000, guidanceObservedAtMs = 16_000,
                locationReceivedElapsedMs = 6_100, guidanceReceivedElapsedMs = 6_100)
            assertFalse(emit("same-event", fresh, 6_100, 16_000).routeActive)
            val recovered = emit("recovered", fresh.copy(nextTurnDistanceMeters = 50, locationObservedAtMs = 17_000,
                locationReceivedElapsedMs = 7_100), 7_100, 17_000)
            assertTrue(recovered.routeActive)
            assertEquals(far.maneuverEventId, recovered.maneuverEventId)
            val next = emit("next-event", fresh.copy(currentStepIndex = 3, guidanceStepIndex = 3,
                locationObservedAtMs = 17_000, locationReceivedElapsedMs = 7_100), 7_100, 17_000)
            assertTrue(next.routeActive)
            assertNotEquals(far.maneuverEventId, next.maneuverEventId)
            gate.disarm()
            assertFalse(emit("stopped", fresh, 6_100, 16_000).routeActive)
        }
        File("build/navassist/control-integration.json").apply {
            parentFile.mkdirs()
            writeText(CanonicalJson.encode(packets), Charsets.UTF_8)
        }
    }
}
