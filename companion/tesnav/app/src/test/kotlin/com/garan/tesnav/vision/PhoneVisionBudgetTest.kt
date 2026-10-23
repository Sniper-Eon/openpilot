package com.garan.tesnav.vision

import org.junit.Assert.*
import org.junit.Test

class PhoneVisionBudgetTest {
    @Test fun serverWaitIsNotDoubleCountedAndDoesNotExtendCaptureDeadline() {
        assertFalse(PhoneVisionBudget.canSubmit(150.0, 600))
        assertTrue(PhoneVisionBudget.canSubmit(150.0, 600, 100.0))
        assertFalse(PhoneVisionBudget.canSubmit(150.0, 700, 100.0))
        assertFalse(PhoneVisionBudget.canSubmit(0.0, 701, 100.0))
        for (bad in listOf(Double.NaN, Double.POSITIVE_INFINITY, -1.0, 1000.0))
            assertFalse(PhoneVisionBudget.canSubmit(150.0, 600, bad))
    }

    @Test fun fastRetryOnlyMatchesActualExpiredResponse() {
        val expired = """{"error":"stale_or_out_of_order_result"}"""
        assertTrue(PhoneVisionBudget.isExpiredRejection(400, expired))
        assertFalse(PhoneVisionBudget.isExpiredRejection(401, expired))
        assertFalse(PhoneVisionBudget.isExpiredRejection(400, """{"error":"unknown_or_replayed_request"}"""))
        assertFalse(PhoneVisionBudget.isExpiredRejection(400, "not JSON"))
        assertFalse(PhoneVisionBudget.isExpiredRejection(503, """{"error":"camera_unavailable_or_stale"}"""))
    }

    @Test fun includesSourceAgeAndPostReserve() {
        assertTrue(PhoneVisionBudget.canSubmit(200.0, 500))
        assertFalse(PhoneVisionBudget.canSubmit(250.0, 500))
        assertTrue(PhoneVisionBudget.canSubmit(0.0, 700))
        assertFalse(PhoneVisionBudget.canSubmit(0.0, 701))
    }
    @Test fun rejectsBrokenAgesAndClockRollback() {
        for (age in listOf(Double.NaN, Double.POSITIVE_INFINITY, -1.0))
            assertFalse(PhoneVisionBudget.canSubmit(age, 100))
        assertFalse(PhoneVisionBudget.canSubmit(0.0, -1))
    }
    @Test fun oldBridgeStillKeepsOriginalLocalDeadline() {
        assertTrue(PhoneVisionBudget.canSubmit(null, 700))
        assertFalse(PhoneVisionBudget.canSubmit(null, 701))
    }
}
