package com.garan.tesnav.vision

import ai.onnxruntime.TensorInfo
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import java.io.Closeable
import java.nio.FloatBuffer
import kotlin.math.min
import kotlin.math.roundToInt

internal class PhoneVehicleDetector(context: Context, cpuThreads: Int = 2, modelAsset: String = "side_vehicle320.onnx") : Closeable {
    var lastTimingsMs: Map<String, Long> = emptyMap()
        private set
    private val environment = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private val inputSize: Int
    init {
        require(modelAsset in setOf("side_vehicle320.onnx", "side_vehicle416.onnx", "side_vehicle640.onnx"))
        val model = context.assets.open(modelAsset).use { it.readBytes() }
        // A bounded CPU pool works without device-specific accelerator support.
        OrtSession.SessionOptions().use { options ->
            options.setIntraOpNumThreads(cpuThreads.coerceIn(1, 4))
            options.setInterOpNumThreads(1)
            val loaded = environment.createSession(model, options)
            try {
                val shape = (loaded.inputInfo["images"]?.info as? TensorInfo)?.shape
                    ?: error("模型缺少图像输入")
                require(shape.size == 4 && shape[0] == 1L && shape[1] == 3L && shape[2] == shape[3] &&
                    shape[2] in longArrayOf(320, 416, 640)) { "模型输入尺寸不支持" }
                inputSize = shape[2].toInt()
                session = loaded
            } catch (e: Exception) { loaded.close(); throw e }
        }
    }

    fun detect(bitmap: Bitmap): List<VehicleBox> {
        val clockStart = android.os.SystemClock.elapsedRealtimeNanos()
        val size = inputSize
        val scale = min(size.toDouble() / bitmap.width, size.toDouble() / bitmap.height)
        val w = (bitmap.width * scale).roundToInt(); val h = (bitmap.height * scale).roundToInt()
        val dx = (size - w) / 2; val dy = (size - h) / 2
        val square = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        try {
            val canvas = Canvas(square); canvas.drawColor(Color.rgb(114, 114, 114))
            canvas.drawBitmap(bitmap, null, Rect(dx, dy, dx + w, dy + h), Paint(Paint.FILTER_BITMAP_FLAG))
            val pixels = IntArray(size * size)
            square.getPixels(pixels, 0, size, 0, 0, size, size)
            val input = FloatArray(3 * pixels.size)
            for (i in pixels.indices) {
                input[i] = ((pixels[i] shr 16) and 255) / 255f
                input[i + pixels.size] = ((pixels[i] shr 8) and 255) / 255f
                input[i + 2 * pixels.size] = (pixels[i] and 255) / 255f
            }
            OnnxTensor.createTensor(environment, FloatBuffer.wrap(input), longArrayOf(1, 3, size.toLong(), size.toLong())).use { tensor ->
                val beforeRun = android.os.SystemClock.elapsedRealtimeNanos()
                session.run(mapOf("images" to tensor)).use { result ->
                    val afterRun = android.os.SystemClock.elapsedRealtimeNanos()
                    @Suppress("UNCHECKED_CAST")
                    val output = result[0].value as Array<Array<FloatArray>>
                    val boxes = SideVehicleGeometry.decode(output[0], bitmap.width, bitmap.height, size)
                    val afterDecode = android.os.SystemClock.elapsedRealtimeNanos()
                    lastTimingsMs = mapOf("preprocess_ms" to (beforeRun-clockStart)/1_000_000,
                        "inference_ms" to (afterRun-beforeRun)/1_000_000,
                        "output_ms" to (afterDecode-afterRun)/1_000_000)
                    return boxes
                }
            }
        } finally { square.recycle() }
    }
    override fun close() { session.close() }
}
