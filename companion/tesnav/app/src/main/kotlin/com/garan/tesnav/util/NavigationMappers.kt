package com.garan.tesnav.util

import com.garan.tesnav.model.CameraType
import com.garan.tesnav.model.LaneAction
import com.garan.tesnav.model.NavigationManeuver
import com.garan.tesnav.model.TrafficStatus

object NavigationMappers {
    /** Keeps a maneuver on the exit/ramp path when AMap's next step starts on an ordinary link. */
    fun maneuverRoadType(nextRoadType: Int?, currentStepRoadTypes: Iterable<Int?>, currentRoadType: Int?): Int? =
        nextRoadType.takeIf(::isExitOrRampRoadType)
            ?: currentStepRoadTypes.firstOrNull(::isExitOrRampRoadType)
            ?: nextRoadType
            ?: currentRoadType

    /** Maps documented AMap IconType integer values to the shared NavAssist vocabulary. */
    fun maneuver(raw: Int?, roadType: Int? = null): NavigationManeuver {
        val direction = when (raw) {
            0, 1 -> NavigationManeuver.NONE
            2 -> NavigationManeuver.TURN_LEFT
            3 -> NavigationManeuver.TURN_RIGHT
            4 -> NavigationManeuver.SLIGHT_LEFT
            5 -> NavigationManeuver.SLIGHT_RIGHT
            6 -> NavigationManeuver.SHARP_LEFT
            7 -> NavigationManeuver.SHARP_RIGHT
            8 -> NavigationManeuver.U_TURN_LEFT
            9, 20 -> NavigationManeuver.STRAIGHT
            11, 12, 17, 18, in 21..28 -> NavigationManeuver.ROUNDABOUT
            15 -> NavigationManeuver.DESTINATION
            19 -> NavigationManeuver.U_TURN_RIGHT
            65 -> NavigationManeuver.MERGE_LEFT
            66 -> NavigationManeuver.MERGE_RIGHT
            10, 13, 14, 16 -> NavigationManeuver.NONE
            else -> NavigationManeuver.UNKNOWN
        }
        return when {
            roadType == ROAD_TYPE_EXIT -> direction.exitVariant()
            roadType in RAMP_ROAD_TYPES -> direction.rampVariant()
            else -> direction
        }
    }

    fun maneuverWireValue(maneuver: NavigationManeuver): String = when (maneuver) {
        NavigationManeuver.NONE -> "none"
        NavigationManeuver.STRAIGHT -> "straight"
        NavigationManeuver.SLIGHT_LEFT -> "slight_left"
        NavigationManeuver.SLIGHT_RIGHT -> "slight_right"
        NavigationManeuver.TURN_LEFT -> "turn_left"
        NavigationManeuver.TURN_RIGHT -> "turn_right"
        NavigationManeuver.SHARP_LEFT -> "sharp_left"
        NavigationManeuver.SHARP_RIGHT -> "sharp_right"
        NavigationManeuver.U_TURN_LEFT -> "u_turn_left"
        NavigationManeuver.U_TURN_RIGHT -> "u_turn_right"
        NavigationManeuver.KEEP_LEFT -> "keep_left"
        NavigationManeuver.KEEP_RIGHT -> "keep_right"
        NavigationManeuver.MERGE_LEFT -> "merge_left"
        NavigationManeuver.MERGE_RIGHT -> "merge_right"
        NavigationManeuver.EXIT_LEFT -> "exit_left"
        NavigationManeuver.EXIT_RIGHT -> "exit_right"
        NavigationManeuver.RAMP_LEFT -> "ramp_left"
        NavigationManeuver.RAMP_RIGHT -> "ramp_right"
        NavigationManeuver.ROUNDABOUT -> "roundabout"
        NavigationManeuver.DESTINATION -> "destination"
        NavigationManeuver.UNKNOWN -> "unknown"
    }

    fun validRoadClass(raw: Int?): Int? = raw?.takeIf { it in 0..10 }

    fun validRoadType(raw: Int?): Int? = raw?.takeIf { it in VALID_ROAD_TYPES }

    fun laneRecommendedActions(laneCount: Int, frontLane: IntArray?): List<List<LaneAction>> =
        List(laneCount.coerceAtLeast(0)) { index ->
            when (val raw = frontLane?.getOrNull(index)) {
                null, 15, 22, 255 -> emptyList()
                else -> laneActions(raw)
            }
        }

    fun laneActions(raw: Int): List<LaneAction> = when (raw) {
        0 -> listOf(LaneAction.STRAIGHT)
        1 -> listOf(LaneAction.LEFT)
        2 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT)
        3 -> listOf(LaneAction.RIGHT)
        4 -> listOf(LaneAction.STRAIGHT, LaneAction.RIGHT)
        5 -> listOf(LaneAction.U_TURN)
        6 -> listOf(LaneAction.LEFT, LaneAction.RIGHT)
        7 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT, LaneAction.RIGHT)
        8 -> listOf(LaneAction.RIGHT_U_TURN)
        9 -> listOf(LaneAction.STRAIGHT, LaneAction.U_TURN)
        10 -> listOf(LaneAction.STRAIGHT, LaneAction.RIGHT_U_TURN)
        11, 14, 20 -> listOf(LaneAction.LEFT, LaneAction.U_TURN)
        12, 17 -> listOf(LaneAction.RIGHT, LaneAction.RIGHT_U_TURN)
        16 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT, LaneAction.U_TURN)
        18 -> listOf(LaneAction.LEFT, LaneAction.RIGHT_U_TURN)
        19 -> listOf(LaneAction.STRAIGHT, LaneAction.RIGHT, LaneAction.RIGHT_U_TURN)
        21 -> listOf(LaneAction.BUS)
        23 -> listOf(LaneAction.VARIABLE)
        24 -> listOf(LaneAction.DEDICATED)
        25 -> listOf(LaneAction.TIDAL)
        else -> listOf(LaneAction.UNKNOWN)
    }

    /** Exact documented AMap LaneAction semantics for the isolated v2 wire path. */
    fun navAssistV2LaneActions(raw: Int): List<LaneAction> = when (raw) {
        0 -> listOf(LaneAction.STRAIGHT)
        1 -> listOf(LaneAction.LEFT)
        2 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT)
        3 -> listOf(LaneAction.RIGHT)
        4 -> listOf(LaneAction.STRAIGHT, LaneAction.RIGHT)
        5 -> listOf(LaneAction.LEFT_U_TURN)
        6 -> listOf(LaneAction.LEFT, LaneAction.RIGHT)
        7 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT, LaneAction.RIGHT)
        8 -> listOf(LaneAction.RIGHT_U_TURN)
        9 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT_U_TURN)
        10 -> listOf(LaneAction.STRAIGHT, LaneAction.RIGHT_U_TURN)
        11, 14 -> listOf(LaneAction.LEFT, LaneAction.LEFT_U_TURN)
        12 -> listOf(LaneAction.RIGHT, LaneAction.RIGHT_U_TURN)
        13 -> listOf(LaneAction.STRAIGHT)
        16 -> listOf(LaneAction.STRAIGHT, LaneAction.LEFT, LaneAction.LEFT_U_TURN)
        17 -> listOf(LaneAction.RIGHT, LaneAction.LEFT_U_TURN)
        18 -> listOf(LaneAction.LEFT, LaneAction.RIGHT, LaneAction.LEFT_U_TURN)
        19 -> listOf(LaneAction.STRAIGHT, LaneAction.RIGHT, LaneAction.LEFT_U_TURN)
        20 -> listOf(LaneAction.LEFT, LaneAction.RIGHT_U_TURN)
        21 -> listOf(LaneAction.BUS)
        23 -> listOf(LaneAction.VARIABLE)
        24 -> listOf(LaneAction.DEDICATED)
        25 -> listOf(LaneAction.TIDAL)
        15, 22, 255 -> emptyList()
        else -> listOf(LaneAction.UNKNOWN)
    }

    fun cameraType(raw: Int): CameraType = when (raw) {
        0 -> CameraType.SPEED
        1 -> CameraType.SURVEILLANCE
        2 -> CameraType.TRAFFIC_LIGHT
        3 -> CameraType.VIOLATION
        4 -> CameraType.BUS_LANE
        5 -> CameraType.EMERGENCY
        6 -> CameraType.BICYCLE
        8 -> CameraType.INTERVAL_START
        9 -> CameraType.INTERVAL_END
        10 -> CameraType.FLOW_SPEED
        11 -> CameraType.ETC
        else -> CameraType.UNKNOWN
    }

    fun trafficStatus(raw: Int): TrafficStatus = when (raw) {
        1 -> TrafficStatus.SMOOTH
        2 -> TrafficStatus.SLOW
        3 -> TrafficStatus.CONGESTED
        4 -> TrafficStatus.SEVERELY_CONGESTED
        else -> TrafficStatus.UNKNOWN
    }

    fun validSpeedLimit(value: Int?): Int? = value?.takeIf { it in 1..300 }

    private val VALID_ROAD_TYPES = setOf(
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 53, 56, 58,
    )
    // AMap RoadType.ENTRANCE (10) uses the existing directional ramp path.
    private val RAMP_ROAD_TYPES = setOf(6, 8, 10, 56, 58)
    private const val ROAD_TYPE_EXIT = 9

    private fun isExitOrRampRoadType(raw: Int?): Boolean = raw != null && (raw == ROAD_TYPE_EXIT || raw in RAMP_ROAD_TYPES)

    private fun NavigationManeuver.exitVariant(): NavigationManeuver = when (this) {
        NavigationManeuver.SLIGHT_LEFT, NavigationManeuver.TURN_LEFT, NavigationManeuver.SHARP_LEFT,
        NavigationManeuver.U_TURN_LEFT, NavigationManeuver.MERGE_LEFT, NavigationManeuver.KEEP_LEFT -> NavigationManeuver.EXIT_LEFT
        NavigationManeuver.SLIGHT_RIGHT, NavigationManeuver.TURN_RIGHT, NavigationManeuver.SHARP_RIGHT,
        NavigationManeuver.U_TURN_RIGHT, NavigationManeuver.MERGE_RIGHT, NavigationManeuver.KEEP_RIGHT -> NavigationManeuver.EXIT_RIGHT
        else -> this
    }

    private fun NavigationManeuver.rampVariant(): NavigationManeuver = when (this) {
        NavigationManeuver.SLIGHT_LEFT, NavigationManeuver.TURN_LEFT, NavigationManeuver.SHARP_LEFT,
        NavigationManeuver.U_TURN_LEFT, NavigationManeuver.MERGE_LEFT, NavigationManeuver.KEEP_LEFT -> NavigationManeuver.RAMP_LEFT
        NavigationManeuver.SLIGHT_RIGHT, NavigationManeuver.TURN_RIGHT, NavigationManeuver.SHARP_RIGHT,
        NavigationManeuver.U_TURN_RIGHT, NavigationManeuver.MERGE_RIGHT, NavigationManeuver.KEEP_RIGHT -> NavigationManeuver.RAMP_RIGHT
        else -> this
    }
}
