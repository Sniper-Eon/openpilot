package com.garan.tesnav.ui

import com.garan.tesnav.model.LaneState
import com.garan.tesnav.model.NavigationMode
import com.garan.tesnav.model.NavigationState
import com.garan.tesnav.model.OemLanePosition
import com.garan.tesnav.model.OemVehicleLaneState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class AutoOvertakeDeciderTest {
    @Test
    fun `OEM permission and clear blindspots cannot establish overtake coverage`() {
        val decision = AutoOvertakeDecider.decide(
            NavigationState(navigationMode = NavigationMode.REALTIME),
            eligibleVehicle(),
        )

        assertFalse(decision.eligible)
        assertEquals(AutoOvertakeAction.KEEP, decision.action)
        assertEquals("能力未就绪：缺少邻道前后覆盖", decision.reason)
    }

    @Test
    fun `neither side is suggested for any OEM position or permission combination`() {
        for (position in OemLanePosition.values()) {
            for (flags in 0..15) {
                val decision = AutoOvertakeDecider.decide(
                    NavigationState(navigationMode = NavigationMode.REALTIME),
                    eligibleVehicle().copy(
                        position = position,
                        leftAllowed = flags and 1 != 0,
                        rightAllowed = flags and 2 != 0,
                        leftBlindspot = flags and 4 != 0,
                        rightBlindspot = flags and 8 != 0,
                    ),
                )
                assertFalse("$position/$flags", decision.eligible)
                assertEquals(AutoOvertakeAction.KEEP, decision.action)
            }
        }
    }

    @Test
    fun `unknown position remains unknown even when valid bit is set`() {
        val decision = AutoOvertakeDecider.decide(
            NavigationState(navigationMode = NavigationMode.REALTIME),
            eligibleVehicle().copy(position = OemLanePosition.UNKNOWN),
        )
        assertFalse(decision.eligible)
        assertEquals("原车车道位置未知", decision.reason)
    }

    @Test
    fun `non finite observations are reported as invalid`() {
        for (value in listOf(Float.NaN, Float.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY)) {
            for (vehicle in listOf(
                eligibleVehicle().copy(egoSpeedKph = value),
                eligibleVehicle().copy(leadDistanceM = value),
                eligibleVehicle().copy(leadRelativeSpeedKph = value),
            )) {
                val decision = AutoOvertakeDecider.decide(
                    NavigationState(navigationMode = NavigationMode.REALTIME), vehicle,
                )
                assertFalse(decision.eligible)
                assertEquals("车辆速度或距离数据无效", decision.reason)
            }
        }
    }

    @Test
    fun `AMap guidance suppresses opportunistic overtake`() {
        val decision = AutoOvertakeDecider.decide(
            NavigationState(
                navigationMode = NavigationMode.REALTIME,
                lanes = listOf(LaneState(index = 0, recommended = true)),
            ),
            eligibleVehicle(),
        )

        assertFalse(decision.eligible)
        assertEquals(AutoOvertakeAction.KEEP, decision.action)
    }

    @Test
    fun `missing vehicle permission fails closed`() {
        val decision = AutoOvertakeDecider.decide(
            NavigationState(navigationMode = NavigationMode.REALTIME),
            eligibleVehicle().copy(permissionValid = false),
        )

        assertFalse(decision.eligible)
        assertEquals(AutoOvertakeAction.KEEP, decision.action)
    }

    private fun eligibleVehicle() = OemVehicleLaneState(
        position = OemLanePosition.MIDDLE,
        positionValid = true,
        leftAllowed = true,
        rightAllowed = true,
        permissionValid = true,
        blindspotValid = true,
        leftBlindspot = false,
        rightBlindspot = false,
        radarValid = true,
        leadPresent = true,
        leadDistanceM = 35f,
        leadRelativeSpeedKph = -10f,
        vehicleStateValid = true,
        egoSpeedKph = 60f,
        lateralActive = true,
    )
}
