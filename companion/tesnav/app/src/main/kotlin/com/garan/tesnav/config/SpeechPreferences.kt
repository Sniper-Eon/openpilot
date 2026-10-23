package com.garan.tesnav.config

import android.content.Context

class SpeechPreferences(context: Context) {
    private val preferences = context.getSharedPreferences("navigation_speech", Context.MODE_PRIVATE)
    val mode: SpeechMode get() = SpeechMode.fromValue(preferences.getInt("mode", 1))
    val resumedMode: SpeechMode get() = SpeechMode.fromValue(preferences.getInt("audible_mode", 1))
        .takeUnless { it == SpeechMode.MUTED } ?: SpeechMode.CONCISE

    fun save(mode: SpeechMode) {
        preferences.edit().apply {
            putInt("mode", mode.value)
            if (mode != SpeechMode.MUTED) putInt("audible_mode", mode.value)
        }.apply()
    }
}
