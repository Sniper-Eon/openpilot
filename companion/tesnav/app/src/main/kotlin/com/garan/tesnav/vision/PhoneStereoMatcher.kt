package com.garan.tesnav.vision

import android.content.Context
import android.graphics.Bitmap
import com.google.gson.Gson
import org.opencv.android.OpenCVLoader
import org.opencv.android.Utils
import org.opencv.calib3d.Calib3d
import org.opencv.core.*
import org.opencv.features2d.BFMatcher
import org.opencv.features2d.SIFT
import org.opencv.imgproc.Imgproc
import java.io.Closeable
import java.security.MessageDigest
import kotlin.math.*

internal data class StereoCameraConfig(val size: List<Int>,val K: List<List<Double>>,val D: List<Double>,val model: String)
internal data class MetricStereoConfig(val version: Int,val validated: Boolean,val units: String,val device_id: String,
    val profile_ids: List<String>,val calibration_pairs: Int,val validation_pairs: Int,
    val stereo_rms_px: Double?,val heldout_rms_px: Double?,val wide: StereoCameraConfig,val narrow: StereoCameraConfig,
    val R_narrow_from_wide: List<List<Double>>,val t_narrow_from_wide_m: List<Double>)

internal class PhoneStereoMatcher private constructor(private val config: MetricStereoConfig,val sha256: String): Closeable {
    private val r=config.R_narrow_from_wide.flatten();private val t=config.t_narrow_from_wide_m
    private val baseline=sqrt(t.sumOf { it*it })
    var lastReason: String="not_started"
        private set
    private val sift=SIFT.create(1200);private val matcher=BFMatcher.create(Core.NORM_L2,false)
    init { Core.setNumThreads(1) }
    companion object {
        fun load(context: Context): PhoneStereoMatcher? {
            val file=java.io.File(context.filesDir,"stereo-calibration.json")
            if(!file.exists())return null
            require(file.length() in 1..65_536) { "双目标定文件大小异常" }
            val bytes=file.readBytes();val config=Gson().fromJson(bytes.toString(Charsets.UTF_8),MetricStereoConfig::class.java)
            validate(config)
            val sha=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
            return try {
                check(OpenCVLoader.initLocal()) { "手机双目计算库未能启动" }
                PhoneStereoMatcher(config,sha)
            } catch(error: LinkageError) {throw IllegalStateException("手机双目计算库不兼容，已停止视觉运算",error)}
        }
        internal fun validate(c: MetricStereoConfig) {
            val trainingRms=c.stereo_rms_px;val validationRms=c.heldout_rms_px
            require(c.version==1 && c.validated && c.units=="metres" && c.device_id.isNotBlank() &&
                c.profile_ids.size==2 && c.profile_ids.all { it.isNotBlank() } && c.profile_ids.distinct().size==2 &&
                c.calibration_pairs>=15 && c.validation_pairs>=5 && trainingRms!=null && trainingRms.isFinite() && trainingRms in 0.0..1.0 &&
                validationRms!=null && validationRms.isFinite() && validationRms in 0.0..1.0) { "双目标定尚未通过验证" }
            for(cam in listOf(c.wide,c.narrow)) {
                require(cam.size.size==2 && cam.size.all { it in 200..4096 } && cam.K.size==3 && cam.K.all { it.size==3 })
                val k=cam.K.flatten()
                require(k.all { it.isFinite() } && k[0]>0 && k[4]>0 && abs(k[1])<1e-6 && abs(k[3])<1e-6 &&
                    k[2] in 0.0..cam.size[0].toDouble() && k[5] in 0.0..cam.size[1].toDouble() &&
                    abs(k[6])+abs(k[7])+abs(k[8]-1)<1e-6 && cam.model in listOf("radtan","fisheye") &&
                    cam.D.size==(if(cam.model=="fisheye") 4 else 5) && cam.D.all { it.isFinite() })
            }
            require(c.R_narrow_from_wide.size==3 && c.R_narrow_from_wide.all { it.size==3 } && c.t_narrow_from_wide_m.size==3)
            val r=c.R_narrow_from_wide.flatten();val t=c.t_narrow_from_wide_m
            require((r+t).all { it.isFinite() } && sqrt(t.sumOf { it*it }) in .01..0.5)
            for(i in 0..2)for(j in 0..2)require(abs((0..2).sumOf { k -> r[k*3+i]*r[k*3+j] }-(if(i==j)1.0 else 0.0))<1e-4)
            val determinant=r[0]*(r[4]*r[8]-r[5]*r[7])-r[1]*(r[3]*r[8]-r[5]*r[6])+r[2]*(r[3]*r[7]-r[4]*r[6])
            require(abs(determinant-1)<1e-4)
        }
    }
    fun associate(wideBitmap: Bitmap,narrowBitmap: Bitmap,wide: List<VehicleBox>,narrow: List<VehicleBox>,pair: DualCameraPair): List<DualMatch> {
        lastReason="geometry_or_uncertainty_rejected"
        require(pair.wide.device_id==config.device_id && pair.narrow.device_id==config.device_id &&
            listOf(pair.wide.calibration_id,pair.narrow.calibration_id)==config.profile_ids) { "相机或设备与标定不匹配" }
        val skew=pair.wide.capture_mono_ns-pair.narrow.capture_mono_ns
        if(abs(skew)>5_000_000) {lastReason="timing_skew";return emptyList()}
        if(wide.size>64 || narrow.size>64 || pair.narrow.view_from_calib?.size!=12) {lastReason="live_pose_unavailable";return emptyList()}
        val mats=mutableListOf<Mat>()
        fun <T:Mat> hold(mat:T):T {mats.add(mat);return mat}
        try {
            val keys=mutableListOf<Array<KeyPoint>>();val desc=mutableListOf<Mat>()
            for((bitmap,boxes) in listOf(wideBitmap to wide,narrowBitmap to narrow)) {
                val rgba=hold(Mat());Utils.bitmapToMat(bitmap,rgba);val gray=hold(Mat());Imgproc.cvtColor(rgba,gray,Imgproc.COLOR_RGBA2GRAY)
                val mask=hold(Mat.zeros(gray.rows(),gray.cols(),CvType.CV_8UC1))
                for(box in boxes)Imgproc.rectangle(mask,Point(box.x1.coerceAtLeast(0.0),box.y1.coerceAtLeast(0.0)),
                    Point(box.x2.coerceAtMost(bitmap.width-1.0),box.y2.coerceAtMost(bitmap.height-1.0)),Scalar(255.0),-1)
                val kp=hold(MatOfKeyPoint());val d=hold(Mat());sift.detectAndCompute(gray,mask,kp,d);keys.add(kp.toArray());desc.add(d)
            }
            if(desc.any { it.rows()<2 }) {lastReason="insufficient_texture";return emptyList()}
            val reverse=hold(MatOfDMatch());matcher.match(desc[1],desc[0],reverse)
            val back=reverse.toArray().associate { it.queryIdx to it.trainIdx }
            val knn=mutableListOf<MatOfDMatch>();matcher.knnMatch(desc[0],desc[1],knn,2);mats.addAll(knn)
            val good=knn.mapNotNull { m ->val a=m.toArray();if(a.size==2 && a[0].distance<.7*a[1].distance && back[a[0].trainIdx]==a[0].queryIdx)a[0] else null }
            if(good.isEmpty()) {lastReason="no_mutual_features";return emptyList()}
            val wp=good.map { keys[0][it.queryIdx].pt };val np=good.map { keys[1][it.trainIdx].pt }
            // Batch undistortion for base points plus eight one-pixel perturbations.
            val allW=mutableListOf<Point>();val allN=mutableListOf<Point>()
            for(variation in 0..8)for(i in wp.indices) {
                val w=Point(wp[i].x,wp[i].y);val n=Point(np[i].x,np[i].y)
                if(variation>0) {
                    val target=if(variation<=4)w else n;val code=(variation-1)%4;val delta=if(code%2==0)-1.0 else 1.0
                    if(code<2)target.x+=delta else target.y+=delta
                }
                allW.add(w);allN.add(n)
            }
            fun undistort(camera: StereoCameraConfig,bitmap: Bitmap,points: List<Point>): Array<Point> {
                require(abs((bitmap.width.toDouble()/bitmap.height)/(camera.size[0].toDouble()/camera.size[1])-1)<.005)
                val values=camera.K.flatten().toDoubleArray();for(i in 0..2)values[i]*=bitmap.width.toDouble()/camera.size[0]
                for(i in 3..5)values[i]*=bitmap.height.toDouble()/camera.size[1]
                val k=hold(Mat(3,3,CvType.CV_64F));k.put(0,0,*values)
                val d=hold(MatOfDouble(*camera.D.toDoubleArray()));val src=hold(MatOfPoint2f(*points.toTypedArray()));val dst=hold(MatOfPoint2f())
                if(camera.model=="fisheye")Calib3d.fisheye_undistortPoints(src,dst,k,d) else Calib3d.undistortPoints(src,dst,k,d)
                return dst.toArray()
            }
            val wr=undistort(config.wide,wideBitmap,allW);val nr=undistort(config.narrow,narrowBitmap,allN)
            val groups=mutableMapOf<Pair<Int,Int>,MutableList<GroundPoint>>()
            fun containing(boxes: List<VehicleBox>,p: Point)=boxes.indices.filter { i ->val b=boxes[i];p.x in b.x1..b.x2 && p.y in b.y1..b.y2 }
            for(i in good.indices) {
                fun solve(v:Int):DoubleArray? {val at=v*good.size+i;return StereoRayGeometry.point(wr[at].x,wr[at].y,nr[at].x,nr[at].y,r,t)}
                val point=solve(0) ?: continue
                if(!StereoRayGeometry.reliable(point,(1..8).map { solve(it) },baseline,skew))continue
                val road=StereoRayGeometry.roadPoint(point,r,t,pair.narrow.view_from_calib) ?: continue
                val a=containing(wide,wp[i]);val b=containing(narrow,np[i])
                if(a.size==1 && b.size==1)groups.getOrPut(a[0] to b[0]) {mutableListOf()}.add(road)
            }
            val supported=groups.filterValues { it.size>=8 }
            val result=supported.mapNotNull { (ids,points) ->
                if(supported.keys.count { it.first==ids.first }>1 || supported.keys.count { it.second==ids.second }>1)return@mapNotNull null
                val x=points.map { it.forward }.sorted();val y=points.map { it.lateral }.sorted();val median=x[x.size/2]
                if(x[x.size*3/4]-x[x.size/4]>max(.5,median*.2))return@mapNotNull null
                DualMatch(ids.first,ids.second,GroundPoint(median,y[y.size/2]),min(wide[ids.first].confidence,narrow[ids.second].confidence))
            }
            if(result.isNotEmpty())lastReason="matched"
            return result
        } finally {mats.asReversed().forEach { it.release() }}
    }
    override fun close() {sift.clear();matcher.clear()}
}
