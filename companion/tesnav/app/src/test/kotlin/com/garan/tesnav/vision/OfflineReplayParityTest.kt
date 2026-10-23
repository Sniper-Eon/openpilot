package com.garan.tesnav.vision

import com.google.gson.*
import java.io.File
import org.junit.Assert.*
import org.junit.Test

class OfflineReplayParityTest {
    private fun number(x: JsonElement?): Double? = x?.takeUnless { it.isJsonNull }?.asDouble
    private fun box(a: JsonArray) = VehicleBox(a[0].asDouble,a[1].asDouble,a[2].asDouble,a[3].asDouble,a[4].asDouble)
    private fun equal(expected: Double?, actual: Double?) {
        if (expected == null) assertNull(actual) else { assertNotNull(actual); assertEquals(expected,actual!!,1e-7) }
    }
    @Test fun replayPortMatchesProductionKotlinCore() {
        val path = System.getenv("PHONE_VISION_PARITY")
        val json = if (path != null) File(path).readText() else {
            requireNotNull(javaClass.getResourceAsStream("/vision/phone-replay-parity.json"))
                .bufferedReader(Charsets.UTF_8).use { it.readText() }
        }
        val root = JsonParser.parseString(json).asJsonObject
        for (entry in root.getAsJsonArray("decode")) {
            val c=entry.asJsonObject
            val input=c.getAsJsonArray("output").map { r -> r.asJsonArray.map { it.asFloat }.toFloatArray() }.toTypedArray()
            val actual=SideVehicleGeometry.decode(input,c["width"].asInt,c["height"].asInt)
            val expected=c.getAsJsonArray("expected")
            assertEquals(expected.size(),actual.size)
            actual.forEachIndexed { i,b ->
                val e=expected[i].asJsonArray
                listOf(b.x1,b.y1,b.x2,b.y2,b.confidence).forEachIndexed { j,v -> equal(e[j].asDouble,v) }
            }
        }
        for (entry in root.getAsJsonArray("distance")) {
            val c=entry.asJsonObject
            val inverse=c["inverse"].takeUnless { it.isJsonNull }?.asJsonArray?.flatMap { it.asJsonArray.map { n -> n.asDouble } }
            equal(number(c["expected"]),SideVehicleGeometry.distance(box(c.getAsJsonArray("box")),inverse,960,601))
        }
        for (entry in root.getAsJsonArray("tracking")) {
            val tracker=SideVehicleTracker()
            for (f in entry.asJsonObject.getAsJsonArray("frames")) {
                val c=f.asJsonObject
                val ds=c.getAsJsonArray("detections").map { x -> x.asJsonObject.let { SideDetection(box(it.getAsJsonArray("box")),it["side"].asString,number(it["distance"])) } }
                val actual=tracker.update(ds,c["t"].asLong,number(c["ego"]))
                val expected=c.getAsJsonObject("expected")
                for (side in listOf("left","right")) {
                    val e=expected[side]
                    val a=actual[side]
                    if (e.isJsonNull) assertNull(a) else {
                        assertNotNull(a);val o=e.asJsonObject
                        assertEquals(o["track_id"].asInt,a!!.track_id);assertEquals(o["hits"].asInt,a.hits)
                        equal(number(o["distance_m"]),a.distance_m);equal(number(o["relative_speed_mps"]),a.relative_speed_mps);equal(number(o["absolute_speed_mps"]),a.absolute_speed_mps)
                    }
                }
            }
        }
    }
}
