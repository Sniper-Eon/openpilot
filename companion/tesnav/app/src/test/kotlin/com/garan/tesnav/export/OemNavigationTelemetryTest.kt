package com.garan.tesnav.export

import com.google.gson.JsonParser
import org.junit.Assert.*
import org.junit.Test

class OemNavigationTelemetryTest {
    @Test fun `source diagnostics accept real five byte accuracy but do not grant permission`() {
        for (raw in listOf("0805060700", "0805060700000000")) {
            val json = fixture()
            json.getAsJsonObject("vehicleTelemetry").apply {
                addProperty("gpsTimeMs", 1790093244712L)
                addProperty("gpsTimeAgeMs", 2000)
                addProperty("gpsPositionAgeMs", 100)
                addProperty("gpsMotionAgeMs", 200)
                addProperty("gpsAccuracyRaw", raw)
                addProperty("gpsAccuracyAgeMs", 300)
            }
            assertTrue(json.toString().toByteArray().size < 1400)
            val lane = parse(json.toString())!!.vehicleLane!!
            assertFalse(lane.permissionValid)
            assertEquals(1790093244712L, lane.navigationTelemetry!!.gpsTimeMs)
            assertEquals(raw, lane.navigationTelemetry!!.gpsAccuracyRaw)
            assertEquals(2000L, lane.navigationTelemetry!!.gpsTimeAgeMs)
            assertNull(lane.forDisplay(1456, 1000).navigationTelemetry)
        }
    }

    @Test fun `malformed or unpaired source diagnostics retain lane ACK only`() {
        for ((key, value) in listOf("gpsTimeMs" to "1790093244712", "gpsTimeAgeMs" to "2500",
            "gpsTimeMs" to "0", "gpsPositionAgeMs" to "-1", "gpsMotionAgeMs" to "1.2",
            "gpsAccuracyRaw" to "\"0805060700\"", "gpsAccuracyRaw" to "\"zzzzzzzzzz\"",
            "gpsAccuracyAgeMs" to "1", "gpsPositionAgeMs" to "\"100\"")) {
            val json = fixture()
            json.getAsJsonObject("vehicleTelemetry").add(key, JsonParser.parseString(value))
            val lane = parse(json.toString())!!.vehicleLane!!
            assertNull("$key=$value", lane.navigationTelemetry)
        }
    }

    private fun fixture() = checkNotNull(javaClass.getResourceAsStream("/navassist/c3-vehicle-telemetry-ack.json"))
        .use { JsonParser.parseString(it.readBytes().decodeToString()).asJsonObject }
    private fun parse(json: String) = NavAssistV3AckParser.parse(
        json.toByteArray(), "192.168.8.101", "00000000-0000-0000-0000-000000000001", 1L, 123L, 456L,
    )

    @Test fun `C3 real CAN sample preserves coordinates and does not change permission`() {
        val json = fixture()
        assertTrue(json.toString().toByteArray().size < 1400)
        val ack = parse(json.toString())!!
        val lane = ack.vehicleLane!!
        val telemetry = lane.navigationTelemetry!!
        assertEquals(32.446709, telemetry.latitude!!, 0.000000001)
        assertEquals(119.902904, telemetry.longitude!!, 0.000000001)
        assertEquals(0.7, telemetry.hdop!!, 0.000001)
        assertEquals(false, telemetry.mapAvailable)
        assertEquals(true, telemetry.navAvailable)
        assertFalse(lane.permissionValid)
        assertEquals("车载 GPS 已接入 · 精度 1.2 米", telemetry.displayText())
        assertNull(telemetry.roadEstimator)
        assertNull(telemetry.oemLaneChangeState)
        assertNull(lane.forDisplay(1456L, 1000L).navigationTelemetry)
    }

    @Test fun `legacy ACK remains accepted and telemetry can arrive without lane feedback`() {
        val json = fixture()
        json.remove("vehicleTelemetry")
        assertNotNull(parse(json.toString())!!.vehicleLane)
        assertNull(parse(json.toString())!!.vehicleLane!!.navigationTelemetry)
        val extended = fixture().apply { remove("vehicleLane") }
        val lane = parse(extended.toString())!!.vehicleLane!!
        assertNotNull(lane.navigationTelemetry)
        assertFalse(lane.permissionValid)
        assertFalse(lane.positionValid)
    }

    @Test fun `invalid telemetry is discarded without losing lane feedback or ACK`() {
        for ((key, bad) in listOf(
            "latitude" to "91", "longitude" to "181", "latitude" to "1e999", "latitude" to "\"32\"",
            "latitude" to "null", "hdop" to "0", "headingDeg" to "360", "speedValue" to "-1",
            "mapAvailable" to "1", "controllerHealth" to "4", "alcState" to "1.0", "navDistanceM" to "25401",
            "gpsStatus" to "\"healthy\"", "gpsStatus" to "\"stale\"",
        )) {
            val json = fixture()
            json.getAsJsonObject("vehicleTelemetry").add(key, JsonParser.parseString(bad))
            val ack = parse(json.toString())!!
            assertNotNull("$key=$bad", ack.vehicleLane)
            assertNull("$key=$bad", ack.vehicleLane!!.navigationTelemetry)
        }
    }

    @Test fun `unavailable observations stay unknown and duplicates cannot override values`() {
        val json = fixture()
        val telemetry = json.getAsJsonObject("vehicleTelemetry")
        for (key in telemetry.keySet().toList()) telemetry.add(key, JsonParser.parseString("null"))
        telemetry.addProperty("gpsStatus", "stale")
        val parsed = parse(json.toString())!!.vehicleLane!!.navigationTelemetry!!
        assertNull(parsed.mapAvailable)
        assertTrue(parsed.displayText().contains("已过期"))
        assertFalse(parsed.displayText().contains("原车地图"))
        assertNull(parse(json.toString().replace("\"gpsStatus\":\"stale\"", "\"gpsStatus\":\"stale\",\"gpsStatus\":\"observed\"")))
    }

    @Test fun `247 diagnostics remain separate from vehicle lane permission`() {
        val json = fixture()
        val telemetry = json.getAsJsonObject("vehicleTelemetry")
        telemetry.addProperty("roadEstimator", 1)
        telemetry.addProperty("oemLaneChangeState", 10)
        val lane = parse(json.toString())!!.vehicleLane!!
        assertFalse(lane.permissionValid)
        assertFalse(lane.leftAllowed)
        assertFalse(lane.rightAllowed)
        val text = lane.navigationTelemetry!!.displayText()
        assertFalse(text.contains("测量不稳定"))
        assertFalse(text.contains("双侧候选"))
        telemetry.addProperty("oemLaneChangeState", 63)
        assertFalse(parse(json.toString())!!.vehicleLane!!.navigationTelemetry!!.displayText().contains("状态码"))
        telemetry.add("roadEstimator", JsonParser.parseString("null"))
        assertNull(parse(json.toString())!!.vehicleLane!!.navigationTelemetry!!.roadEstimator)
        assertNull(lane.forDisplay(1456L, 1000L).navigationTelemetry)
    }

    @Test fun `247 optional fields reject malformed codes without dropping existing lane ACK`() {
        for ((key, bad) in listOf("roadEstimator" to "4", "roadEstimator" to "\"1\"",
            "oemLaneChangeState" to "64", "oemLaneChangeState" to "-1", "oemLaneChangeState" to "1.0",
            "oemLaneChangeState" to "{}")) {
            val json = fixture()
            json.getAsJsonObject("vehicleTelemetry").add(key, JsonParser.parseString(bad))
            val lane = parse(json.toString())!!.vehicleLane!!
            assertNull("$key=$bad", lane.navigationTelemetry)
        }
    }
}
