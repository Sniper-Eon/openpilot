package com.garan.tesnav.model

/** Latest CAN state received from Comma over WebSocket. */
data class CommaState(
    val timestampMs: Long = 0L,
    val isTeslaNavActive: Boolean = false,
)
