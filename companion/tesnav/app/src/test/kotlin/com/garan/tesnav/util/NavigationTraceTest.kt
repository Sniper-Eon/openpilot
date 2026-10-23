package com.garan.tesnav.util

import java.io.File
import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

class NavigationTraceTest {
    @Test fun busyTripRetainsMoreThanFourFilesAndPreservesContents() {
        val dir = Files.createTempDirectory("navigation-trace").toFile()
        try {
            val now = System.currentTimeMillis()
            for (i in 1..12) {
                File(dir, "sdk.log.$i").apply { writeText("part-$i"); setLastModified(now - i * 60_000L) }
            }
            File(dir, "sdk.log").writeText("current")
            NavigationTrace.rotate(dir, now)
            assertEquals("current", File(dir, "sdk.log.1").readText())
            for (i in 1..12) assertEquals("part-$i", File(dir, "sdk.log.${i + 1}").readText())
        } finally { dir.deleteRecursively() }
    }

    @Test fun expirationPreservesBoundaryAndUnrelatedFiles() {
        val dir = Files.createTempDirectory("navigation-trace").toFile()
        try {
            val now = 1_800_000_000_000L
            val boundary = now - 2 * 60 * 60 * 1000L
            File(dir, "sdk.log").writeText("current")
            File(dir, "sdk.log.1").apply { writeText("boundary"); assertTrue(setLastModified(boundary)) }
            File(dir, "sdk.log.2").apply { writeText("expired"); assertTrue(setLastModified(boundary - 1)) }
            File(dir, "sdk.log.3").apply { writeText("future-clock"); assertTrue(setLastModified(now + 1000)) }
            File(dir, "notes.txt").writeText("keep")
            NavigationTrace.rotate(dir, now)
            assertEquals("boundary", File(dir, "sdk.log.2").readText())
            assertEquals("future-clock", File(dir, "sdk.log.4").readText())
            assertEquals("keep", File(dir, "notes.txt").readText())
            assertFalse(dir.listFiles()!!.any { it.readText() == "expired" })
        } finally { dir.deleteRecursively() }
    }
}
