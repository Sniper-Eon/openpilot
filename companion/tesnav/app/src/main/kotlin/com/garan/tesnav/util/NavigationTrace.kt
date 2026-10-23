package com.garan.tesnav.util

import java.io.File
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Debug evidence independent of adb; retain at least two hours of available events. */
internal object NavigationTrace {
    private const val MAX_FILE_BYTES = 8L * 1024 * 1024
    private const val RETENTION_MS = 2L * 60 * 60 * 1000
    private val dropped = AtomicInteger()
    private val writer = ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
        ArrayBlockingQueue<Runnable>(128),
        { runnable -> Thread(runnable, "navigation-trace").apply { isDaemon = true } },
        { _, _ -> dropped.incrementAndGet(); Unit })

    fun append(filesDir: File, line: String, tag: String = "TesNav-AMap") {
        val timestamp = System.currentTimeMillis()
        val pid = android.os.Process.myPid()
        writer.execute {
            runCatching {
                val directory = File(filesDir, "navigation-trace")
                directory.mkdirs()
                val file = File(directory, "sdk.log")
                if (file.length() >= MAX_FILE_BYTES) {
                    rotate(directory, System.currentTimeMillis())
                }
                val lost = dropped.getAndSet(0)
                file.appendText("${timestamp / 1000}.${(timestamp % 1000).toString().padStart(3, '0')} $pid $pid D $tag: $line traceDropped=$lost\n")
            }
        }
    }

    // Only completed files older than the retention window may be removed.
    // Keep the boundary file in full; a busy trip can therefore use more than four files.
    internal fun rotate(directory: File, nowMs: Long) {
        val archives = directory.listFiles().orEmpty().mapNotNull { file ->
            val index = file.name.removePrefix("sdk.log.").toIntOrNull()
            if (file.name.startsWith("sdk.log.") && index != null && index > 0 && file.isFile) {
                index to file
            } else null
        }.sortedByDescending { it.first }
        for ((index, file) in archives) {
            if (file.lastModified() > 0 && file.lastModified() < nowMs - RETENTION_MS) {
                check(file.delete()) { "Cannot remove expired navigation trace" }
            } else {
                check(index < Int.MAX_VALUE && file.renameTo(File(directory, "sdk.log.${index + 1}"))) {
                    "Cannot rotate navigation trace"
                }
            }
        }
        check(File(directory, "sdk.log").renameTo(File(directory, "sdk.log.1"))) {
            "Cannot archive navigation trace"
        }
    }
}
