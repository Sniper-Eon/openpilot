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
        val description = TextView(this).apply { text = "使用 C3 广角画面，在手机上运算。距离与速度为实验估算，当前仅供观察。" }
        val host = EditText(this).apply { hint = "C3 地址"; setSingleLine(true)
            setText(preferences.getString("host", intent.getStringExtra("c3_host") ?: "comma-904f361e.local")) }
        val token = EditText(this).apply { hint = "设备连接码"; setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(preferences.getString("token", "")) }
        val status = TextView(this).apply { textSize = 18f; setPadding(0, 24, 0, 24) }
        val start = Button(this).apply { text = "开始手机运算"; setOnClickListener {
            if (host.text.isBlank() || token.text.length < 32) { Toast.makeText(this@PhoneVisionActivity, "请填写 C3 地址与连接码", Toast.LENGTH_SHORT).show(); return@setOnClickListener }
            preferences.edit().putString("host", host.text.toString().trim()).putString("token", token.text.toString().trim()).apply()
            startForegroundService(Intent(this@PhoneVisionActivity, PhoneVisionService::class.java))
        } }
        val stop = Button(this).apply { text = "停止"; setOnClickListener { stopService(Intent(this@PhoneVisionActivity, PhoneVisionService::class.java)); PhoneVisionService.status.value = "已停止" } }
        val back = Button(this).apply { text = "返回导航，保持运算"; setOnClickListener { finish() } }
        listOf(title, description, host, token, start, stop, back, status).forEach { layout.addView(it) }
        setContentView(ScrollView(this).apply { addView(layout) })
        scope.launch { PhoneVisionService.status.collect { status.text = it } }
    }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}
