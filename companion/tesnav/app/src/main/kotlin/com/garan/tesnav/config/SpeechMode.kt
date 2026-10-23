package com.garan.tesnav.config

enum class SpeechMode(val value: Int, val title: String) {
    CONCISE(1, "简洁播报（较少）"), DETAILED(2, "详细播报（较多）"), MUTED(0, "静音");

    companion object {
        fun fromValue(value: Int): SpeechMode = entries.firstOrNull { it.value == value } ?: CONCISE
    }
}
