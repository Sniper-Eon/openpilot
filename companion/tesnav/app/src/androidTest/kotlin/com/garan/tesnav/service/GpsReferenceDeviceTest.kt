package com.garan.tesnav.service

import android.content.Context
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amap.api.maps.CoordinateConverter
import com.amap.api.maps.model.LatLng
import com.garan.tesnav.config.AmapConfiguration
import com.google.gson.Gson
import java.io.File
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Independent raw-phone reference only. Does not start navigation or publish to C3. */
@RunWith(AndroidJUnit4::class)
class GpsReferenceDeviceTest {
    @Test fun collectRawGpsAndSdkCoordinateConversion() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val queue = LinkedBlockingQueue<Location>(128)
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) { queue.offer(Location(location)) }
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}
            @Deprecated("Legacy Android callback")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }
        val rows = mutableListOf<Map<String, Any?>>()
        val startedWallMs = System.currentTimeMillis()
        try {
            assertTrue("No configured SDK key", AmapConfiguration.prepare(context))
            instrumentation.runOnMainSync {
                manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, listener, Looper.getMainLooper())
            }
            val deadline = SystemClock.elapsedRealtime() + 25_000L
            while (SystemClock.elapsedRealtime() < deadline) {
                val location = queue.poll(250, TimeUnit.MILLISECONDS) ?: continue
                val converted = CoordinateConverter(context).from(CoordinateConverter.CoordType.GPS)
                    .coord(LatLng(location.latitude, location.longitude)).convert()
                rows.add(mapOf("receivedWallMs" to System.currentTimeMillis(),
                    "sourceWallMs" to location.time, "sourceElapsedNs" to location.elapsedRealtimeNanos,
                    "receivedElapsedNs" to SystemClock.elapsedRealtimeNanos(),
                    "latitudeWgs" to location.latitude, "longitudeWgs" to location.longitude,
                    "latitudeGcj" to converted.latitude, "longitudeGcj" to converted.longitude,
                    "accuracyM" to if (location.hasAccuracy()) location.accuracy else null,
                    "speedMps" to if (location.hasSpeed()) location.speed else null,
                    "mock" to location.isFromMockProvider))
            }
        } finally {
            instrumentation.runOnMainSync { manager.removeUpdates(listener) }
            File(context.filesDir, "gps-reference-test.json").writeText(Gson().toJson(
                mapOf("startedWallMs" to startedWallMs, "endedWallMs" to System.currentTimeMillis(),
                    "navigationStarted" to false, "controlPublished" to false, "rows" to rows)))
        }
        assertTrue("No raw GPS observation available; see gps-reference-test.json", rows.isNotEmpty())
    }
}
