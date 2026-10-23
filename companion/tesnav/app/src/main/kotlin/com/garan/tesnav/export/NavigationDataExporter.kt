package com.garan.tesnav.export

import kotlinx.coroutines.flow.StateFlow

enum class ExportConnectionState { STOPPED, STARTING, CONNECTED, ERROR }

data class ExportConfig(
    val enabled: Boolean,
    val webSocketUrl: String,
    val apiToken: String,
    val intervalMs: Long,
)

interface NavigationDataExporter {
    val connectionState: StateFlow<ExportConnectionState>
    val lastError: StateFlow<String?>
    fun start()
    fun stop()
}
