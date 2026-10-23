package com.garan.tesnav.vision

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

class LatestVisionFramesTest {
    private suspend fun waitFor(condition: () -> Boolean) = withTimeout(2000) {
        while (!condition()) delay(1)
    }
    @Test fun slowInferenceGetsNewestWaitingFrameWithoutOverlappingDownloads() = runBlocking {
        val input = Channel<Int>(Channel.UNLIMITED)
        val inFlight = AtomicInteger(); val maximum = AtomicInteger()
        val source = LatestVisionFrames(this, 0, {
            val active = inFlight.incrementAndGet(); maximum.updateAndGet { maxOf(it, active) }
            try { input.receive() } finally { inFlight.decrementAndGet() }
        }, { throw AssertionError(it) }, { System.nanoTime()/1_000_000 })
        try {
            input.send(1); assertEquals(1, withTimeout(2000) { source.next() })
            // While inference works on 1, four more captures arrive.
            for (i in 2..5) input.send(i)
            waitFor { source.completedFetches.get() >= 5 }
            assertEquals(5, withTimeout(2000) { source.next() })
            assertEquals(1, maximum.get())
            input.send(6); assertEquals(6, withTimeout(2000) { source.next() })
        } finally { source.close(); input.cancel() }
    }
    @Test fun transportFailureDiscardsPendingFrameAndCanRecover() = runBlocking {
        val input = Channel<Result<Int>>(Channel.UNLIMITED)
        val failed = Channel<Unit>(1)
        val source = LatestVisionFrames(this, 0, { input.receive().getOrThrow() },
            { failed.trySend(Unit) }, { System.nanoTime()/1_000_000 }, errorDelayMs=0)
        try {
            input.send(Result.success(1)); waitFor { source.completedFetches.get() == 1L }
            input.send(Result.failure(IllegalStateException("network lost")))
            withTimeout(2000) { failed.receive() }
            val pending = async { source.next() }; yield()
            assertFalse(pending.isCompleted)
            input.send(Result.success(2)); assertEquals(2, withTimeout(2000) { pending.await() })
        } finally { source.close(); input.cancel(); failed.cancel() }
    }
    @Test fun stoppingCancelsDownloadAndClosesPendingConsumer() = runBlocking {
        val started = CompletableDeferred<Unit>(); val cancelled = CompletableDeferred<Unit>()
        val source = LatestVisionFrames<Int>(this, 0, {
            started.complete(Unit)
            try { awaitCancellation() } finally { cancelled.complete(Unit) }
        }, { throw AssertionError(it) }, { System.nanoTime()/1_000_000 })
        withTimeout(2000) { started.await() }; source.close()
        withTimeout(2000) { cancelled.await() }
        assertTrue(runCatching { source.next() }.exceptionOrNull() is CancellationException)
    }
}
