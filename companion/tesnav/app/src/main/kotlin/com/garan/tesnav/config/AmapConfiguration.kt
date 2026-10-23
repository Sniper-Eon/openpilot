package com.garan.tesnav.config

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import com.amap.api.location.AMapLocationClient
import com.amap.api.maps.MapsInitializer
import com.amap.api.navi.AMapNavi
import com.amap.api.services.core.ServiceSettings
import java.security.MessageDigest

object AmapConfiguration {
    private const val PREFS = "amap_configuration"
    private const val KEY = "sdk_key"
    private var appliedKey: String? = null

    fun effectiveKey(context: Context): String? {
        val saved = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
        @Suppress("DEPRECATION")
        val bundled = context.packageManager.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA)
            .metaData?.getString("com.amap.api.v2.apikey")
        return AmapKeyPolicy.resolve(saved, bundled)
    }

    fun save(context: Context, raw: String): Boolean {
        val value = AmapKeyPolicy.normalized(raw) ?: return false
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, value).commit()
    }

    @Synchronized
    fun prepare(context: Context): Boolean {
        val key = effectiveKey(context) ?: return false
        if (appliedKey == key) return true
        MapsInitializer.updatePrivacyShow(context, true, true)
        MapsInitializer.updatePrivacyAgree(context, true)
        AMapLocationClient.updatePrivacyShow(context, true, true)
        AMapLocationClient.updatePrivacyAgree(context, true)
        ServiceSettings.updatePrivacyShow(context, true, true)
        ServiceSettings.updatePrivacyAgree(context, true)
        MapsInitializer.setApiKey(key)
        AMapLocationClient.setApiKey(key)
        ServiceSettings.getInstance().setApiKey(key)
        AMapNavi.setApiKey(context, key)
        appliedKey = key
        return true
    }

    fun signingSha1(context: Context): String = runCatching {
        @Suppress("DEPRECATION")
        val signatures = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
                .signingInfo?.apkContentsSigners.orEmpty()
        } else {
            context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_SIGNATURES).signatures.orEmpty()
        }
        signatures.joinToString("\n") { signature ->
            MessageDigest.getInstance("SHA-1").digest(signature.toByteArray())
                .joinToString(":") { "%02X".format(it.toInt() and 0xff) }
        }
    }.getOrDefault("")
}
