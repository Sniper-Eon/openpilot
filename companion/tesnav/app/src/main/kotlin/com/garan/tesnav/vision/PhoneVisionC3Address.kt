package com.garan.tesnav.vision

import java.net.URI

/** Reuse the C3 endpoint already discovered by navigation; never reuse its service port. */
internal object PhoneVisionC3Address {
    @Volatile var navigationHost: String? = null
}

internal fun visionHostFromNavigationEndpoint(endpoint: String?): String? = runCatching {
    val uri = URI(endpoint ?: return null)
    if (uri.scheme !in setOf("udp", "http", "https") || uri.userInfo != null) return null
    uri.host?.takeIf { it.matches(Regex("[A-Za-z0-9.-]+")) }
}.getOrNull()
