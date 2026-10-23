package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test

class VisionAvailabilityTest {
    @Test fun stalledInferenceCannotLeaveOldVehiclesOnTheScreenForever() {
        var text = ""
        val state = VisionAvailability { text = it }
        state.accepted(1000, "previous result")
        state.expire(2000)
        assertEquals("previous result", text)
        state.expire(2001)
        assertEquals("视觉不可用：识别结果已超时", text)
    }
    @Test fun retriesDoNotRenewOldEvidenceAndRecoveryRequiresANewAcceptedResult() {
        var text = ""
        val state = VisionAvailability { text = it }
        state.accepted(1000, "old")
        state.unavailable("连接失败")
        state.expire(1500)
        assertEquals("视觉不可用：连接失败", text)
        state.accepted(2000, "new")
        state.expire(2100)
        assertEquals("new", text)
    }
    @Test fun clockRollbackAlsoInvalidatesDisplay() {
        var text = ""
        val state = VisionAvailability { text = it }
        state.accepted(1000, "old")
        state.expire(999)
        assertTrue(text.startsWith("视觉不可用"))
    }
    @Test fun serviceStopDoesNotHideAnExistingFailureReason() {
        var text = ""
        val state = VisionAvailability { text = it }
        state.unavailable("等待 C3 相机启动")
        state.stopped()
        assertEquals("视觉不可用：等待 C3 相机启动", text)
        state.accepted(1000, "old")
        state.stopped()
        assertEquals("视觉不可用：服务已停止", text)
    }
}
