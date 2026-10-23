package com.garan.tesnav

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.garan.tesnav.config.AmapConfiguration
import com.garan.tesnav.config.AmapKeyPolicy

class AmapKeyActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val existing = AmapConfiguration.effectiveKey(this)
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(32), dp(24), dp(32))
            setBackgroundColor(Color.rgb(246, 248, 252))
        }
        fun label(value: String, size: Float = 16f) = TextView(this).apply {
            text = value
            textSize = size
            setTextColor(Color.rgb(30, 41, 59))
            setPadding(0, dp(8), 0, dp(8))
            setLineSpacing(dp(3).toFloat(), 1.1f)
        }
        fun button(value: String, action: () -> Unit) {
            body.addView(Button(this).apply { text = value; setOnClickListener { action() } })
        }
        body.addView(label("连接高德导航", 28f).apply { setTypeface(typeface, Typeface.BOLD) })
        body.addView(label(if (existing == null) "首次使用，请先填写高德 Android Key。配置保存在本机，之后无需重复填写。"
                          else "高德 Key 已配置。你可以在这里查看申请说明或更换 Key。"))
        val input = EditText(this).apply {
            id = android.R.id.edit
            hint = "粘贴 32 位高德 Android Key"
            setSingleLine(true)
            textSize = 17f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(existing.orEmpty())
            contentDescription = "高德 Android Key"
        }
        body.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(58)))
        button("显示 / 隐藏 Key") {
            val showing = input.transformationMethod == null
            input.transformationMethod = if (showing) android.text.method.PasswordTransformationMethod.getInstance() else null
            input.setSelection(input.text.length)
        }
        val error = label("").apply { setTextColor(Color.rgb(185, 28, 28)) }
        body.addView(error)
        button("保存并进入") {
            val key = AmapKeyPolicy.normalized(input.text.toString())
            if (key == null) {
                error.text = "请输入完整的 32 位 Key，不要填写安全密钥、网址或 iOS Key。"
            } else if (!AmapConfiguration.save(this, key)) {
                error.text = "保存失败，请重试。"
            } else {
                startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
                finish()
            }
        }
        body.addView(label("如何申请 Key", 21f).apply { setTypeface(typeface, Typeface.BOLD) })
        body.addView(label("1. 打开高德开放平台控制台，注册 / 登录并按提示完成账号认证。\n\n2. 进入「应用管理 → 我的应用」，创建应用并添加 Key，服务平台选择「Android 平台 SDK」。\n\n3. 填写下方包名和当前安装包签名 SHA-1。调试版、发布版的安全码可能不同，请按安装包对应的类型填写。\n\n4. 创建后复制 Key，返回本页粘贴并保存。地图、搜索、定位和导航将使用此 Key。"))
        body.addView(label("应用包名\n$packageName"))
        button("复制包名") { copy("Package", packageName) }
        val sha1 = AmapConfiguration.signingSha1(this)
        body.addView(label("当前安装包 SHA-1\n${sha1.ifEmpty { "暂时无法读取签名" }}").apply { textSize = 14f })
        if (sha1.isNotEmpty()) button("复制 SHA-1") { copy("SHA-1", sha1) }
        body.addView(label("Android 与 iOS 的 Key 不能互用。若提示鉴权失败，请核对平台、包名、签名与高德账号服务权限。Key 保存成功不代表高德已通过鉴权。", 14f))
        button("打开高德控制台") { open("https://console.amap.com/") }
        button("查看官方 Android 配置说明") { open("https://lbs.amap.com/api/android-navi-sdk/guide/create-project/get-key") }
        if (existing != null) button("返回") { finish() }
        setContentView(ScrollView(this).apply { isFillViewport = true; addView(body) })
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun copy(label: String, value: String) {
        (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText(label, value))
        Toast.makeText(this, "已复制", Toast.LENGTH_SHORT).show()
    }
    private fun open(url: String) {
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            .onFailure { Toast.makeText(this, "无法打开浏览器", Toast.LENGTH_SHORT).show() }
    }
}
