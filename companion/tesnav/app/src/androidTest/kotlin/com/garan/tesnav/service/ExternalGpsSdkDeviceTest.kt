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
import com.amap.api.navi.AMapNavi
import com.amap.api.navi.SimpleNaviListener
import com.amap.api.navi.model.AMapNaviLocation
import com.garan.tesnav.config.AmapConfiguration
import com.google.gson.Gson
import java.io.File
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** API plumbing only, using fresh PHONE reference measurements, not unqualified OEM GPS.
 * No route is planned, navigation started, exporter created or vehicle command published.
 */
@RunWith(AndroidJUnit4::class)
class ExternalGpsSdkDeviceTest {
    @Test fun enableFeedAndDisableExternalGpsInterface() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val queue = LinkedBlockingQueue<Location>(16)
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) { queue.offer(Location(location)) }
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}
            @Deprecated("Legacy Android callback")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }
        var engine: AMapNavi? = null
        var fed = false
        var disabled = false
        val callbacks = LinkedBlockingQueue<Map<String, Any?>>(128)
        val injectedTimes = mutableSetOf<Long>()
        val injectedSamples = mutableListOf<Map<String, Any>>()
        val observedCallbacks = mutableListOf<Map<String, Any?>>()
        var associatedCallbacks = 0
        val navigationListener = object : SimpleNaviListener() {
            override fun onLocationChange(location: AMapNaviLocation?) {
                if (location == null) return
                callbacks.offer(mapOf("time" to location.time, "receivedElapsedMs" to SystemClock.elapsedRealtime(), "latitude" to location.coord?.latitude,
                    "longitude" to location.coord?.longitude, "matched" to location.isMatchNaviPath))
            }
        }
        try {
            assertTrue(AmapConfiguration.prepare(context))
            instrumentation.runOnMainSync {
                manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, listener, Looper.getMainLooper())
                engine = AMapNavi.getInstance(context)
                engine!!.addAMapNaviListener(navigationListener)
                engine!!.stopGPS()
            }
            val deadline = SystemClock.elapsedRealtime()+15_000
            var observed: Location? = null
            while (SystemClock.elapsedRealtime()<deadline && observed==null) {
                val sample=queue.poll(250,TimeUnit.MILLISECONDS) ?: continue
                val age=SystemClock.elapsedRealtimeNanos()-sample.elapsedRealtimeNanos
                if (age in 0L..2_000_000_000L && sample.hasAccuracy() && sample.hasSpeed() &&
                    sample.hasBearing() && !sample.isFromMockProvider) observed=sample
            }
            val sample=checkNotNull(observed) { "Fresh complete reference GPS unavailable" }
            val gcj=CoordinateConverter(context).from(CoordinateConverter.CoordType.GPS)
                .coord(LatLng(sample.latitude,sample.longitude)).convert()
            val input=Location(sample).apply { latitude=gcj.latitude; longitude=gcj.longitude }
            instrumentation.runOnMainSync {
                checkNotNull(engine).setIsUseExtraGPSData(true)
                checkNotNull(engine).setExtraGPSData(2,input)
                fed=true
            }
            injectedTimes.add(input.time)
            injectedSamples.add(mapOf("time" to input.time,"elapsedMs" to SystemClock.elapsedRealtime(),
                "latitude" to input.latitude,"longitude" to input.longitude,"accuracyM" to input.accuracy,"speedMps" to input.speed))
            val callbackDeadline = SystemClock.elapsedRealtime()+10_000
            while (SystemClock.elapsedRealtime()<callbackDeadline) {
                val next = queue.poll(200,TimeUnit.MILLISECONDS)
                if (next != null && next.time > injectedTimes.max() &&
                    SystemClock.elapsedRealtimeNanos()-next.elapsedRealtimeNanos in 0L..2_000_000_000L &&
                    next.hasAccuracy() && next.hasSpeed() && next.hasBearing() && !next.isFromMockProvider) {
                    val point=CoordinateConverter(context).from(CoordinateConverter.CoordType.GPS)
                        .coord(LatLng(next.latitude,next.longitude)).convert()
                    val fix=Location(next).apply { latitude=point.latitude;longitude=point.longitude }
                    instrumentation.runOnMainSync { engine!!.setExtraGPSData(2,fix) }
                    injectedTimes.add(fix.time)
                    injectedSamples.add(mapOf("time" to fix.time,"elapsedMs" to SystemClock.elapsedRealtime(),
                        "latitude" to fix.latitude,"longitude" to fix.longitude,"accuracyM" to fix.accuracy,"speedMps" to fix.speed))
                }
                callbacks.drainTo(observedCallbacks)
            }
            associatedCallbacks=observedCallbacks.count { it["time"] in injectedTimes }
            val afterFeeding = SystemClock.elapsedRealtime()
            val silentDeadline=afterFeeding+4_000
            while (SystemClock.elapsedRealtime()<silentDeadline) {
                callbacks.poll(200,TimeUnit.MILLISECONDS)?.let { observedCallbacks.add(it) }
            }
            instrumentation.runOnMainSync { engine!!.setIsUseExtraGPSData(false); disabled=true }
            assertEquals(sample.time,input.time)
            assertTrue("SDK emitted no location callback", observedCallbacks.isNotEmpty())
            val aligned = observedCallbacks.filter { (it["receivedElapsedMs"] as Long) < afterFeeding }.count { callback ->
                val lat=callback["latitude"] as? Double
                val lon=callback["longitude"] as? Double
                lat!=null && lon!=null && injectedSamples.any { fix ->
                    val distances=FloatArray(1)
                    Location.distanceBetween(lat,lon,fix["latitude"] as Double,fix["longitude"] as Double,distances)
                    distances[0]<=50f
                }
            }
            assertTrue("No output was within 50m of a supplied reference point", aligned>0)
        } finally {
            instrumentation.runOnMainSync {
                manager.removeUpdates(listener)
                try { engine?.setIsUseExtraGPSData(false) } finally {
                    engine?.removeAMapNaviListener(navigationListener)
                    engine?.stopGPS()
                    if (engine!=null) AMapNavi.destroy()
                }
            }
            File(context.filesDir,"gps-external-interface-test.json").writeText(Gson().toJson(mapOf(
                "externalFeedReturned" to fed,"disableReturned" to disabled,"sampleSource" to "phoneReferenceConvertedGcj02",
                "injectedSamples" to injectedTimes.size,"callbackCount" to observedCallbacks.size,
                "inputs" to injectedSamples,
                "sourceTimeAssociatedCallbacks" to associatedCallbacks,"callbacks" to observedCallbacks,
                "oemFallbackTested" to false,"navigationStarted" to false,"controlPublished" to false)))
        }
    }
}
