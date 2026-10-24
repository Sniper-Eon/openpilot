package com.garan.tesnav.vision

import android.content.Context
import android.graphics.BitmapFactory
import android.os.SystemClock
import android.util.Base64
import com.google.gson.Gson
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import java.util.concurrent.TimeUnit

internal data class DualCameraImage(val version: Int,val frame_id: Long,val capture_mono_ns: Long,
    val width: Int,val height: Int,val jpeg_b64: String,val ego_speed_mps: Double?,val ground_inverse: List<Double>?,
    val capture_age_ms: Double?,val camera_id: String,val calibration_id: String?,val device_id: String?,
    val view_from_calib: List<Double>?)
internal data class DualCameraPair(val version: Int, val pair_id: String, val stream_id: String,
    val wide: DualCameraImage, val narrow: DualCameraImage, val skew_ms: Double, val bridge_wait_ms: Double?)

/** Two-camera observation session; no navigation/exporter/control requests. */
internal class DualCameraSession(private val context: Context, private val host: String, private val token: String,
                                 private val threads: Int, private val availability: VisionAvailability,
                                 private val report: (Map<String,Any>)->Unit) {
    private data class DownloadedPair(val pair: DualCameraPair,val host: String,val endpoint: String,
        val requestedMs: Long,val downloadedMs: Long)
    suspend fun run() = coroutineScope {
        val client=OkHttpClient.Builder().connectTimeout(2,TimeUnit.SECONDS).readTimeout(3,TimeUnit.SECONDS).callTimeout(4,TimeUnit.SECONDS).build()
        val gson=Gson();var tracker=DualGroundTracker();var identity: String?=null;var lastCapture=-1L
        val stereo=PhoneStereoMatcher.load(context)
        fun newTracker()=DualGroundTracker(if(stereo==null)"dual_ground_estimate" else "stereo_experimental")
        tracker=newTracker()
        val downloads=LatestVisionFrames(this,333L, {
            val requested=SystemClock.elapsedRealtime()
            val activeHost=PhoneVisionC3Address.navigationHost ?: host
            require(activeHost.matches(Regex("[A-Za-z0-9.-]+(?::[0-9]{1,5})?")))
            val endpoint="http://"+activeHost+if(':' in activeHost) "" else ":8767"
            val request=Request.Builder().url("$endpoint/v2/pair").header("Authorization","Bearer $token").build()
            val pair=client.newCall(request).execute().use { response ->
                check(response.isSuccessful) { when(response.code) {404->"C3 尚未启用双相机观察";503->"等待两路相机同步画面";else->"双相机连接失败（${response.code}）"} }
                val body=response.body ?: error("双相机画面为空")
                check(body.contentLength() in 1..3_000_000) { "双相机画面大小异常" }
                gson.fromJson(body.string(),DualCameraPair::class.java)
            }
            DownloadedPair(pair,activeHost,endpoint,requested,SystemClock.elapsedRealtime())
        }, { e -> availability.unavailable(e.message ?: "等待双相机画面") },SystemClock::elapsedRealtime)
        var attempts=0L;var accepted=0L;var expired=0L
        try { PhoneVehicleDetector(context,threads).use { detector ->
            while(currentCoroutineContext().isActive) {
                val iteration=SystemClock.elapsedRealtime()
                val timing=linkedMapOf<String,Any>("mode" to "dual_observation","attempt" to ++attempts,
                    "onnx_threads" to threads,"prefetch" to true)
                try {
                    val downloaded=downloads.next()
                    val pair=downloaded.pair;val activeHost=downloaded.host;val endpoint=downloaded.endpoint
                    val start=downloaded.requestedMs
                    timing["fetch_ms"]=downloaded.downloadedMs-start
                    timing["queue_wait_ms"]=SystemClock.elapsedRealtime()-downloaded.downloadedMs
                    timing["bridge_wait_ms"]=pair.bridge_wait_ms ?: -1.0
                    timing["capture_age_ms"]=maxOf(pair.wide.capture_age_ms ?: -1.0,pair.narrow.capture_age_ms ?: -1.0)
                    check(pair.version==2 && pair.wide.camera_id=="wide" && pair.narrow.camera_id=="narrow") { "相机身份不匹配" }
                    check(pair.skew_ms.isFinite() && pair.skew_ms in 0.0..50.0) { "两路画面不同步" }
                    val actualSkew=kotlin.math.abs(pair.wide.capture_mono_ns-pair.narrow.capture_mono_ns)/1e6
                    check(kotlin.math.abs(actualSkew-pair.skew_ms)<.001) { "拍摄时间不一致" }
                    fun fresh() {
                        if(activeHost != (PhoneVisionC3Address.navigationHost ?: host)) throw ExpiredVisionFrame()
                        for(frame in listOf(pair.wide,pair.narrow)) {
                            check(frame.version==1 && frame.width in 320..1928 && frame.height in 200..1208)
                            check(frame.capture_age_ms!=null) { "双相机缺少拍摄时效" }
                            if(!PhoneVisionBudget.canSubmit(frame.capture_age_ms,SystemClock.elapsedRealtime()-start,pair.bridge_wait_ms)) throw ExpiredVisionFrame()
                        }
                    }
                    fresh()
                    val key=listOf(activeHost,pair.stream_id,pair.wide.calibration_id,pair.narrow.calibration_id).joinToString("|")
                    if(key!=identity) {identity=key;tracker=newTracker();lastCapture=-1L}
                    val capture=minOf(pair.wide.capture_mono_ns,pair.narrow.capture_mono_ns)
                    if(capture<=lastCapture) throw ExpiredVisionFrame()
                    fun decode(frame: DualCameraImage): android.graphics.Bitmap {
                        val bytes=Base64.decode(frame.jpeg_b64,Base64.DEFAULT)
                        val options=BitmapFactory.Options().apply { inJustDecodeBounds=true }
                        BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)
                        check(options.outWidth==frame.width && options.outHeight==frame.height) { "相机图像尺寸不符" }
                        return BitmapFactory.decodeByteArray(bytes,0,bytes.size) ?: error("相机图像解码失败")
                    }
                    var wide=emptyList<VehicleBox>();var narrow=emptyList<VehicleBox>();var matches=emptyList<DualMatch>()
                    var stage=SystemClock.elapsedRealtime()
                    val wb=decode(pair.wide)
                    timing["wide_decode_ms"]=SystemClock.elapsedRealtime()-stage
                    try {
                        stage=SystemClock.elapsedRealtime();wide=detector.detect(wb)
                        timing["wide_detect_ms"]=SystemClock.elapsedRealtime()-stage
                        timing["wide_inference_ms"]=detector.lastTimingsMs["inference_ms"] ?: -1L
                        fresh();stage=SystemClock.elapsedRealtime();val nb=decode(pair.narrow)
                        timing["narrow_decode_ms"]=SystemClock.elapsedRealtime()-stage
                        try {
                            stage=SystemClock.elapsedRealtime();narrow=detector.detect(nb)
                            timing["narrow_detect_ms"]=SystemClock.elapsedRealtime()-stage
                            timing["narrow_inference_ms"]=detector.lastTimingsMs["inference_ms"] ?: -1L
                            fresh();stage=SystemClock.elapsedRealtime()
                            matches=if(stereo!=null)stereo.associate(wb,nb,wide,narrow,pair)
                                else if(pair.wide.calibration_id.isNullOrBlank() || pair.narrow.calibration_id.isNullOrBlank()) emptyList()
                                else DualGroundGeometry.associate(wide,narrow,pair.wide.ground_inverse,pair.narrow.ground_inverse,
                                    pair.wide.width,pair.wide.height,pair.narrow.width,pair.narrow.height,pair.skew_ms)
                            timing["match_ms"]=SystemClock.elapsedRealtime()-stage
                        } finally { nb.recycle() }
                    } finally { wb.recycle() }
                    fresh()
                    val observations=tracker.update(matches,wide,capture,pair.wide.ego_speed_mps)
                    val payload=mapOf("pair_id" to pair.pair_id,"stream_id" to pair.stream_id,"wide_frame_id" to pair.wide.frame_id,
                        "narrow_frame_id" to pair.narrow.frame_id,"tracks" to observations,"stereo_calibration_sha256" to stereo?.sha256)
                    val post=Request.Builder().url("$endpoint/v2/observation").header("Authorization","Bearer $token")
                        .post(gson.toJson(payload).toRequestBody("application/json".toMediaType())).build()
                    currentCoroutineContext().ensureActive();fresh()
                    stage=SystemClock.elapsedRealtime()
                    client.newCall(post).execute().use { response ->
                        if(!response.isSuccessful) {
                            val body=response.body?.string().orEmpty().take(8192)
                            if(PhoneVisionBudget.isExpiredRejection(response.code,body)) throw ExpiredVisionFrame()
                            error("双相机观察结果被拒绝（${response.code}）")
                        }
                    }
                    timing["post_ms"]=SystemClock.elapsedRealtime()-stage
                    accepted++
                    lastCapture=capture
                    val nearest=observations.minByOrNull { it.distance_m }
                    val label=if(stereo==null)"地面估计" else "双目实验估计"
                    val detail=nearest?.let { "$label %.1f 米".format(it.distance_m)+
                        (it.relative_speed_mps?.let { speed -> "；相对趋势 %+.1f km/h".format(speed*3.6) } ?: "；趋势积累中") }
                        ?: when(stereo?.lastReason) {"timing_skew"->"同步精度不足，暂不给距离";"live_pose_unavailable"->"等待有效相机标定姿态";else->"纹理、视差或连续确认不足，距离暂不可用"}
                    val limits=if(stereo==null)"地面投影匹配；双目标定未完成" else "标定后的纹理点匹配；实际误差尚未验证"
                    availability.accepted(start,"双相机观察：广角 ${wide.size} 个框，窄角 ${narrow.size} 个框\n同车候选 ${matches.size} 个，连续确认 ${observations.size} 个\n$detail\n$limits，不作为变道许可")
                    timing.putAll(mapOf("mode" to "dual_observation","outcome" to "accepted","wide_boxes" to wide.size,"narrow_boxes" to narrow.size,
                        "matches" to matches.size,"tracks" to observations.size,"skew_ms" to pair.skew_ms,"total_ms" to SystemClock.elapsedRealtime()-start,
                        "stereo_calibration_loaded" to (stereo!=null),"stereo_reason" to (stereo?.lastReason ?: "not_calibrated"),
                        "opencv_threads" to 1,"onnx_threads" to threads,"control_eligible" to false))
                } catch(e: Exception) {
                    if(e is CancellationException) throw e
                    tracker=newTracker();lastCapture=-1L
                    availability.unavailable(e.message ?: "等待双相机画面")
                    if(e is ExpiredVisionFrame) expired++
                    timing["outcome"]="unavailable";timing["error_type"]=e.javaClass.simpleName
                    // A stale frame must not impose a one-second outage on fresh frames.
                    // Real transport/protocol failures keep their bounded backoff.
                    delay(if(e is ExpiredVisionFrame) 50L else 1000L)
                } finally {
                    timing["accepted_total"]=accepted;timing["expired_total"]=expired
                    timing["fetch_total"]=downloads.completedFetches.get()
                    timing["iteration_ms"]=SystemClock.elapsedRealtime()-iteration
                    timing["report_elapsed_ms"]=SystemClock.elapsedRealtime()
                    report(timing)
                }
            }
        } } finally {downloads.close();stereo?.close()}
    }
}
