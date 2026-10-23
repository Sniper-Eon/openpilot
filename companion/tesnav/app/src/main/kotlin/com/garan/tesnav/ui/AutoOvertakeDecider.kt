package com.garan.tesnav.ui

import com.garan.tesnav.model.NavigationMode
import com.garan.tesnav.model.NavigationState
import com.garan.tesnav.model.OemLanePosition
import com.garan.tesnav.model.OemVehicleLaneState

enum class AutoOvertakeAction { KEEP, LEFT, RIGHT }

data class AutoOvertakeDecision(
    val action: AutoOvertakeAction,
    val eligible: Boolean,
    val reason: String,
)

/** Reports capability limits; current feedback cannot establish an overtake direction. */
object AutoOvertakeDecider {
    fun decide(nav: NavigationState, vehicle: OemVehicleLaneState): AutoOvertakeDecision {
        fun keep(reason: String) = AutoOvertakeDecision(AutoOvertakeAction.KEEP, false, reason)
        if (nav.navigationMode != NavigationMode.REALTIME) return keep("非实时导航")
        if (!vehicle.vehicleStateValid || !vehicle.radarValid || !vehicle.blindspotValid) return keep("车辆传感器数据无效")
        if (!vehicle.positionValid || !vehicle.permissionValid) return keep("车道或变道状态无效")
        if (vehicle.position == OemLanePosition.UNKNOWN) return keep("原车车道位置未知")
        if (!vehicle.lateralActive || vehicle.brakePressed || vehicle.gasPressed) return keep("驾驶控制条件不满足")
        if (vehicle.laneChangeState != 0) return keep("已有变道正在进行")
        if (!vehicle.leadPresent) return keep("前方无车")

        val egoKph = vehicle.egoSpeedKph ?: return keep("无本车速度")
        val leadDistance = vehicle.leadDistanceM ?: return keep("无前车距离")
        val relativeKph = vehicle.leadRelativeSpeedKph ?: return keep("无前车相对速度")
        if (!egoKph.isFinite() || !leadDistance.isFinite() || !relativeKph.isFinite()) {
            return keep("车辆速度或距离数据无效")
        }
        if (egoKph < MIN_EGO_KPH) return keep("车速低于自动超车门限")
        if (leadDistance !in MIN_LEAD_DISTANCE_M..MAX_LEAD_DISTANCE_M) return keep("前车距离不在超车窗口")
        if (relativeKph > MAX_RELATIVE_SPEED_KPH) return keep("前车未明显压速")

        // Keep route guidance distinct from opportunistic overtake diagnostics.
        if (nav.lanes.any { it.recommended || it.prohibited }) return keep("高德推荐或路线避选车道生效")

        // Lead data and clear blindspot flags do not cover adjacent front/rear traffic.
        return keep("能力未就绪：缺少邻道前后覆盖")
    }

    private const val MIN_EGO_KPH = 30f
    private const val MIN_LEAD_DISTANCE_M = 12f
    private const val MAX_LEAD_DISTANCE_M = 80f
    private const val MAX_RELATIVE_SPEED_KPH = -5f
}
