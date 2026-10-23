package com.garan.tesnav.export

import com.garan.tesnav.model.NavigationState
import com.garan.tesnav.model.CommaState
import com.garan.tesnav.model.GeoPoint
import com.garan.tesnav.util.RouteGeometrySimplifier
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

data class NavigationWireEnvelope(
    val schemaVersion: Int = 1,
    val state: NavigationState,
)

data class RouteWireEnvelope(
    val schemaVersion: Int = 1,
    val route: RouteWireData,
)

data class RouteWireData(
    val revision: Long,
    val available: Boolean,
    val pathId: Long? = null,
    val totalDistanceMeters: Int? = null,
    val sourcePointCount: Int = 0,
    val toleranceMeters: Double? = null,
    val points: List<GeoPoint> = emptyList(),
)

private data class CommaWireEnvelope(
    val schemaVersion: Int,
    val timestampMs: Long,
    val data: CommaWireData?,
)

private data class CommaWireData(
    @SerializedName("is_tesla_nav_active")
    val isTeslaNavActive: Boolean,
)

/** Persistent WebSocket transport that publishes the newest snapshot every 200 ms. */
class WebSocketNavigationDataExporter(
    private val config: ExportConfig,
    private val stateProvider: () -> NavigationState?,
    private val onCommaState: (CommaState) -> Unit,
) : NavigationDataExporter {
    private val mutableConnectionState = MutableStateFlow(ExportConnectionState.STOPPED)
    override val connectionState: StateFlow<ExportConnectionState> = mutableConnectionState
    private val mutableLastError = MutableStateFlow<String?>(null)
    override val lastError: StateFlow<String?> = mutableLastError

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .pingInterval(5, TimeUnit.SECONDS)
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    @Volatile private var running = false
    @Volatile private var socket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var publisherJob: Job? = null
    private val routeRevision = AtomicLong(0L)
    @Volatile private var latestRouteEnvelope: RouteWireEnvelope? = null

    override fun start() {
        if (!config.enabled || config.webSocketUrl.isBlank() || running) return
        running = true
        connect()
    }

    override fun stop() {
        running = false
        reconnectJob?.cancel()
        reconnectJob = null
        publisherJob?.cancel()
        publisherJob = null
        socket?.close(1000, "service stopped")
        socket = null
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
        client.dispatcher.executorService.shutdown()
        scope.cancel()
        mutableConnectionState.value = ExportConnectionState.STOPPED
    }

    private fun connect() {
        if (!running) return
        mutableConnectionState.value = ExportConnectionState.STARTING
        val request = Request.Builder().url(config.webSocketUrl).apply {
            if (config.apiToken.isNotBlank()) header("Authorization", "Bearer ${config.apiToken}")
        }.build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                socket = webSocket
                mutableConnectionState.value = ExportConnectionState.CONNECTED
                mutableLastError.value = null
                sendLatestSnapshot()
                sendLatestRoute()
                startFixedRatePublisher()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val envelope = runCatching {
                    gson.fromJson(text, CommaWireEnvelope::class.java)
                }.getOrNull() ?: return
                if (envelope.schemaVersion != 1) return
                val data = envelope.data ?: return
                onCommaState(
                    CommaState(
                        timestampMs = envelope.timestampMs,
                        isTeslaNavActive = data.isTeslaNavActive,
                    ),
                )
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                val wasCurrent = socket === webSocket
                if (wasCurrent) socket = null
                if (running && wasCurrent) scheduleReconnect("连接已关闭：$code $reason")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val wasCurrent = socket === webSocket
                if (wasCurrent) socket = null
                if (running && wasCurrent) scheduleReconnect(t.message ?: t.javaClass.simpleName)
            }
        })
    }

    fun publishRoute(pathId: Long, totalDistanceMeters: Int, points: List<GeoPoint>) {
        val revision = routeRevision.incrementAndGet()
        val sourcePoints = points.toList()
        scope.launch {
            val simplified = RouteGeometrySimplifier.simplifyForViewport(
                points = sourcePoints,
                viewportWidthPixels = ROUTE_REFERENCE_WIDTH_PIXELS,
                viewportHeightPixels = ROUTE_REFERENCE_HEIGHT_PIXELS,
                tolerancePixels = ROUTE_TOLERANCE_PIXELS,
            )
            if (routeRevision.get() != revision) return@launch
            val envelope = RouteWireEnvelope(
                route = RouteWireData(
                    revision = revision,
                    available = true,
                    pathId = pathId,
                    totalDistanceMeters = totalDistanceMeters,
                    sourcePointCount = sourcePoints.size,
                    toleranceMeters = simplified.toleranceMeters,
                    points = simplified.points,
                ),
            )
            latestRouteEnvelope = envelope
            sendRoute(envelope)
        }
    }

    fun clearRoute() {
        val revision = routeRevision.incrementAndGet()
        val envelope = RouteWireEnvelope(
            route = RouteWireData(
                revision = revision,
                available = false,
            ),
        )
        latestRouteEnvelope = envelope
        sendRoute(envelope)
    }

    @Synchronized
    private fun sendLatestSnapshot() {
        val state = stateProvider() ?: return
        val sent = socket?.send(gson.toJson(NavigationWireEnvelope(state = state))) == true
        if (sent) mutableLastError.value = null
        else if (running) scheduleReconnect("WebSocket 发送失败")
    }

    @Synchronized
    private fun sendLatestRoute() {
        latestRouteEnvelope?.let(::sendRoute)
    }

    @Synchronized
    private fun sendRoute(envelope: RouteWireEnvelope) {
        if (mutableConnectionState.value != ExportConnectionState.CONNECTED) return
        val sent = socket?.send(gson.toJson(envelope)) == true
        if (sent) mutableLastError.value = null
        else if (running) scheduleReconnect("WebSocket 路线发送失败")
    }

    @Synchronized
    private fun startFixedRatePublisher() {
        publisherJob?.cancel()
        publisherJob = scope.launch {
            val interval = config.intervalMs.coerceAtLeast(200L)
            while (isActive && running) {
                delay(interval)
                if (mutableConnectionState.value == ExportConnectionState.CONNECTED) sendLatestSnapshot()
            }
        }
    }

    @Synchronized
    private fun scheduleReconnect(message: String) {
        publisherJob?.cancel()
        publisherJob = null
        mutableLastError.value = message
        mutableConnectionState.value = ExportConnectionState.ERROR
        if (reconnectJob?.isActive == true || !running) return
        reconnectJob = scope.launch {
            var waitMs = 1_000L
            while (isActive && running && mutableConnectionState.value != ExportConnectionState.CONNECTED) {
                delay(waitMs)
                connect()
                delay(1_000L)
                waitMs = (waitMs * 2).coerceAtMost(10_000L)
            }
        }
    }

    private companion object {
        const val ROUTE_REFERENCE_WIDTH_PIXELS = 1920.0
        const val ROUTE_REFERENCE_HEIGHT_PIXELS = 1080.0
        const val ROUTE_TOLERANCE_PIXELS = 1.5
    }
}
