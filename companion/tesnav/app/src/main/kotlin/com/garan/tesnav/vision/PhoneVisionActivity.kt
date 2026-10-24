package com.garan.tesnav.vision

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.widget.*
import kotlinx.coroutines.*

class PhoneVisionActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val preferences = getSharedPreferences("phone_vision", MODE_PRIVATE)
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 40, 32, 24) }
        val title = TextView(this).apply { text = "手机侧方车辆识别"; textSize = 24f }
        val description = TextView(this).apply { text = "画面由 C3 提供，在手机上运算。双相机需要本车标定才能尝试立体测距，尚未完成实际误差验证。开启双相机观察会暂停原单路侧车回传，不用于行驶变道辅助。切换模式请先停止运算。" }
        val host = EditText(this).apply { hint = "C3 地址"; setSingleLine(true)
            setText(preferences.getString("host", intent.getStringExtra("c3_host") ?: "comma-904f361e.local")) }
        val token = EditText(this).apply { hint = "设备连接码"; setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(preferences.getString("token", "")) }
        val status = TextView(this).apply { textSize = 18f; setPadding(0, 24, 0, 24) }
        val dual = Switch(this).apply { text="双相机观察（实验）"; isChecked=preferences.getBoolean("dual_camera", false) }
        val start = Button(this).apply { text = "开始手机运算"; setOnClickListener {
            if (host.text.isBlank() || token.text.length < 32) { Toast.makeText(this@PhoneVisionActivity, "请填写 C3 地址与连接码", Toast.LENGTH_SHORT).show(); return@setOnClickListener }
            preferences.edit().putString("host", host.text.toString().trim()).putString("token", token.text.toString().trim())
                .putBoolean("dual_camera", dual.isChecked).apply()
            startForegroundService(Intent(this@PhoneVisionActivity, PhoneVisionService::class.java))
        } }
        val stop = Button(this).apply { text = "停止"; setOnClickListener { stopService(Intent(this@PhoneVisionActivity, PhoneVisionService::class.java)); PhoneVisionService.status.value = "已停止" } }
        val back = Button(this).apply { text = "返回导航，保持运算"; setOnClickListener { finish() } }
        listOf(title, description, host, token, dual, start, stop, back, status).forEach { layout.addView(it) }
        setContentView(ScrollView(this).apply { addView(layout) })
        scope.launch { PhoneVisionService.status.collect { status.text = it } }
    }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}
