package com.garan.tesnav.vision

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.io.Closeable
import java.util.concurrent.atomic.AtomicLong

/** One network request at a time; at most one downloaded frame waits for inference. */
internal class LatestVisionFrames<T>(
    scope: CoroutineScope,
    intervalMs: Long,
    private val fetch: suspend () -> T,
    private val onError: (Exception) -> Unit,
    private val clockMs: () -> Long,
    private val errorDelayMs: Long = 1000,
) : Closeable {
    private val frames = Channel<T>(Channel.CONFLATED)
    val completedFetches = AtomicLong()
    private val worker = scope.launch(Dispatchers.IO) {
        try {
            while (isActive) {
                val start = clockMs()
                try {
                    val frame = fetch()
                    currentCoroutineContext().ensureActive()
                    frames.trySend(frame)
                    completedFetches.incrementAndGet()
                } catch (e: CancellationException) { throw e }
                catch (e: Exception) {
                    // A transport failure cannot leave a queued old frame looking current.
                    frames.tryReceive().getOrNull()
                    onError(e)
                    delay(errorDelayMs)
                }
                delay(maxOf(0L, intervalMs - (clockMs() - start)))
            }
        } finally { frames.close() }
    }
    suspend fun next(): T = frames.receive()
    override fun close() { worker.cancel(); frames.cancel() }
}
