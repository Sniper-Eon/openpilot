package com.garan.tesnav.homeassistant

import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

enum class HomeAssistantConnectionState {
    DISABLED,
    CONNECTING,
    AUTHENTICATING,
    CONNECTED,
    TOKEN_REQUIRED,
    ERROR,
}

data class TeslaNavigationDestination(
    val latitude: Double,
    val longitude: Double,
)

data class HomeAssistantNavigationState(
    val navigationActive: Boolean? = null,
    val destination: TeslaNavigationDestination? = null,
)

/** Subscribes to Tesla navigation state and destination through Home Assistant. */
class HomeAssistantNavigationClient {
    private val mutableConnectionState = MutableStateFlow(HomeAssistantConnectionState.DISABLED)
    val connectionState: StateFlow<HomeAssistantConnectionState> = mutableConnectionState.asStateFlow()
    private val mutableNavigationState = MutableStateFlow(HomeAssistantNavigationState())
    val navigationState: StateFlow<HomeAssistantNavigationState> = mutableNavigationState.asStateFlow()
    private val mutableLastError = MutableStateFlow<String?>(null)
    val lastError: StateFlow<String?> = mutableLastError.asStateFlow()

    private val gson = Gson()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val httpClient = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    @Volatile private var running = false
    @Volatile private var socket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var url = ""
    private var token = ""
    private var navigationActiveEntity: String? = null
    private var navigationDestinationEntity: String? = null

    fun start(url: String, token: String) {
        stop(resetNavigationState = true)
        if (token.isBlank()) {
            mutableConnectionState.value = HomeAssistantConnectionState.TOKEN_REQUIRED
            mutableLastError.value = "请填写 Home Assistant 长期访问令牌"
            return
        }
        this.url = normalizeUrl(url)
        this.token = token.trim()
        running = true
        connect()
    }

    fun stop() = stop(resetNavigationState = true)

    fun release() {
        stop(resetNavigationState = true)
        httpClient.dispatcher.cancelAll()
        httpClient.connectionPool.evictAll()
        httpClient.dispatcher.executorService.shutdown()
        scope.cancel()
    }

    private fun stop(resetNavigationState: Boolean) {
        running = false
        reconnectJob?.cancel()
        reconnectJob = null
        socket?.close(1000, "sync disabled")
        socket = null
        mutableConnectionState.value = HomeAssistantConnectionState.DISABLED
        mutableLastError.value = null
        navigationActiveEntity = null
        navigationDestinationEntity = null
        if (resetNavigationState) mutableNavigationState.value = HomeAssistantNavigationState()
    }

    private fun connect() {
        if (!running) return
        mutableConnectionState.value = HomeAssistantConnectionState.CONNECTING
        socket = httpClient.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (socket !== webSocket) return
                mutableConnectionState.value = HomeAssistantConnectionState.AUTHENTICATING
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (socket !== webSocket) return
                runCatching { handleMessage(webSocket, gson.fromJson(text, JsonObject::class.java)) }
                    .onFailure { fail("Home Assistant 数据格式错误：${it.message}") }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (socket !== webSocket) return
                socket = null
                if (running) scheduleReconnect("连接关闭：$code $reason")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (socket !== webSocket) return
                socket = null
                if (running) scheduleReconnect(t.message ?: t.javaClass.simpleName)
            }
        })
    }

    private fun handleMessage(webSocket: WebSocket, message: JsonObject) {
        when (message.string("type")) {
            "auth_required" -> webSocket.send(gson.toJson(mapOf("type" to "auth", "access_token" to token)))
            "auth_ok" -> {
                mutableConnectionState.value = HomeAssistantConnectionState.CONNECTED
                mutableLastError.value = null
                webSocket.send("{\"id\":1,\"type\":\"get_states\"}")
                webSocket.send("{\"id\":2,\"type\":\"subscribe_events\",\"event_type\":\"state_changed\"}")
            }
            "auth_invalid" -> {
                running = false
                mutableConnectionState.value = HomeAssistantConnectionState.ERROR
                mutableLastError.value = "Home Assistant 令牌认证失败"
                webSocket.close(1008, "authentication failed")
            }
            "result" -> if (message.int("id") == 1 && message.get("success")?.asBoolean == true) {
                message.getAsJsonArray("result")?.forEach(::consumeState)
            }
            "event" -> {
                val event = message.getAsJsonObject("event")
                if (event?.string("event_type") == "state_changed") {
                    event.getAsJsonObject("data")?.getAsJsonObject("new_state")?.let(::consumeState)
                }
            }
        }
    }

    private fun consumeState(element: JsonElement) {
        if (!element.isJsonObject) return
        val state = element.asJsonObject
        val entityId = state.string("entity_id") ?: return
        val friendlyName = state.getAsJsonObject("attributes")?.string("friendly_name").orEmpty()
        val normalized = (entityId + " " + friendlyName).lowercase().replace(Regex("[^a-z0-9]+"), " ")
        val value = state.string("state")
        when {
            normalized.contains("navigation active") -> {
                navigationActiveEntity = entityId
                updateNavigationActive(value)
            }
            normalized.contains("navigation destination") &&
                !normalized.contains("latitude") && !normalized.contains("longitude") -> {
                navigationDestinationEntity = entityId
                updateDestination(value)
            }
            entityId == navigationActiveEntity -> updateNavigationActive(value)
            entityId == navigationDestinationEntity -> updateDestination(value)
        }
    }

    private fun updateNavigationActive(value: String?) {
        val active = value == "on" || value == "true" || value == "1"
        mutableNavigationState.value = mutableNavigationState.value.copy(navigationActive = active)
    }

    private fun updateDestination(value: String?) {
        mutableNavigationState.value = mutableNavigationState.value.copy(destination = parseTeslaDestination(value))
    }

    private fun scheduleReconnect(message: String) {
        mutableConnectionState.value = HomeAssistantConnectionState.ERROR
        mutableNavigationState.value = HomeAssistantNavigationState()
        mutableLastError.value = message
        if (reconnectJob?.isActive == true || !running) return
        reconnectJob = scope.launch {
            var waitMs = 1_000L
            while (isActive && running && mutableConnectionState.value != HomeAssistantConnectionState.CONNECTED) {
                delay(waitMs)
                connect()
                delay(1_000L)
                waitMs = (waitMs * 2).coerceAtMost(15_000L)
            }
        }
    }

    private fun fail(message: String) {
        mutableConnectionState.value = HomeAssistantConnectionState.ERROR
        mutableLastError.value = message
    }

    companion object {
        fun normalizeUrl(input: String): String {
            val base = input.trim().ifBlank { "http://192.168.51.168:8123" }
            val socketBase = when {
                base.startsWith("https://") -> "wss://${base.removePrefix("https://")}" 
                base.startsWith("http://") -> "ws://${base.removePrefix("http://")}" 
                base.startsWith("ws://") || base.startsWith("wss://") -> base
                else -> "ws://$base"
            }.trimEnd('/')
            return if (socketBase.endsWith("/api/websocket")) socketBase else "$socketBase/api/websocket"
        }

        fun parseTeslaDestination(value: String?): TeslaNavigationDestination? {
            val parts = value?.trim()?.split(',') ?: return null
            if (parts.size != 2) return null
            val latitude = parts[0].trim().toDoubleOrNull() ?: return null
            val longitude = parts[1].trim().toDoubleOrNull() ?: return null
            return TeslaNavigationDestination(latitude, longitude)
                .takeIf { latitude in -90.0..90.0 && longitude in -180.0..180.0 }
        }
    }
}

private fun JsonObject.string(name: String): String? = get(name)?.takeUnless { it.isJsonNull }?.asString
private fun JsonObject.int(name: String): Int? = get(name)?.takeUnless { it.isJsonNull }?.asInt
