package com.garan.tesnav.config

object AmapKeyPolicy {
    fun normalized(value: String?): String? = value?.trim()?.takeIf { it.matches(Regex("[a-fA-F0-9]{32}")) }

    fun resolve(saved: String?, bundled: String?): String? =
        if (saved != null) normalized(saved) else normalized(bundled)
}
