package com.garan.tesnav.vision

/** Capture age is measured by C3 when issuing the frame; clocks need not agree. */
internal object PhoneVisionBudget {
    fun isExpiredRejection(status: Int, body: String): Boolean = status == 400 && runCatching {
        com.google.gson.JsonParser.parseString(body).asJsonObject.get("error")?.asString == "stale_or_out_of_order_result"
    }.getOrDefault(false)

    fun canSubmit(captureAgeMs: Double?, elapsedMs: Long, serverWaitMs: Double? = null): Boolean {
        if (elapsedMs < 0 || elapsedMs > 700) return false
        // Older bridges still enforce their original 800 ms capture-age check.
        if (captureAgeMs == null) return true
        // The server wait happened before the JPEG was issued; its time is already
        // represented in source age. Credit only a finite, bounded server wait.
        val creditedWait = serverWaitMs?.takeIf { it.isFinite() && it >= 0 && it <= elapsedMs } ?: 0.0
        return captureAgeMs.isFinite() && captureAgeMs >= 0 && captureAgeMs + elapsedMs - creditedWait + 80 <= 800
    }
}

internal class ExpiredVisionFrame : Exception("画面已过期，正在刷新")
