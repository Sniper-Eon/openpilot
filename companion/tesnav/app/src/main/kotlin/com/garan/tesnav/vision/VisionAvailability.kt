package com.garan.tesnav.vision

/** Display freshness only; this class supplies no driving permission. */
internal class VisionAvailability(private val maxAgeMs: Long = 1000, private val publish: (String) -> Unit) {
    private var acceptedAt: Long? = null

    @Synchronized fun accepted(requestStartedAt: Long, message: String) {
        acceptedAt = requestStartedAt
        publish(message)
    }

    @Synchronized fun unavailable(reason: String) {
        acceptedAt = null
        publish("视觉不可用：$reason")
    }

    @Synchronized fun expire(now: Long) {
        val previous = acceptedAt ?: return
        if (now - previous !in 0..maxAgeMs) unavailable("识别结果已超时")
    }

    @Synchronized fun stopped() {
        if (acceptedAt != null) unavailable("服务已停止")
    }
}
