plugins {
    alias(libs.plugins.android.application)
}

// Keep the navigation SDK's existing libc++ runtime instead of resolving a
// duplicate by archive order. Native-symbol/APK checks accompany this change.
val phoneStereoCvArchive by configurations.creating {
    isCanBeConsumed = false
    isTransitive = false
}
dependencies { add(phoneStereoCvArchive.name, "org.opencv:opencv:4.13.0@aar") }
val preparePhoneStereoCv by tasks.registering(Zip::class) {
    archiveFileName.set("opencv-4.13.0-navigation-stl.aar")
    destinationDirectory.set(layout.buildDirectory.dir("phone-stereo"))
    from(phoneStereoCvArchive.map { zipTree(it) }) {
        exclude("jni/**/libc++_shared.so")
        // Match the navigation SDK's existing ARM ABIs; do not add desktop ABIs.
        exclude("jni/x86/**", "jni/x86_64/**", "jni/riscv64/**")
    }
}

fun String.asBuildConfigString(): String =
    "\"${replace("\\", "\\\\").replace("\"", "\\\"")}\""

android {
    namespace = "com.garan.tesnav"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        val navAssistV2IntervalMs = providers.gradleProperty("NAV_ASSIST_V2_INTERVAL_MS")
            .orNull
            ?.toLongOrNull()
            ?.coerceAtLeast(200L)
            ?: 200L
        applicationId = "com.garan.tesnav"
        minSdk = 26
        targetSdk = 37
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        versionCode = 15
        versionName = "1.3-dual-observer-r11"

        manifestPlaceholders["AMAP_API_KEY"] =
            providers.gradleProperty("AMAP_API_KEY").orNull ?: ""
        manifestPlaceholders["APP_NAME"] = "TesNav"
        buildConfigField("boolean", "EXTENDED_NAV_SOURCES", "false")
        buildConfigField("boolean", "EXPORT_ENABLED", providers.gradleProperty("EXPORT_ENABLED").orNull ?: "true")
        buildConfigField("String", "WEBSOCKET_URL", "\"${providers.gradleProperty("WEBSOCKET_URL").orNull ?: "ws://192.168.53.232:7766/amap-navigation"}\"")
        buildConfigField("String", "API_TOKEN", "\"${providers.gradleProperty("API_TOKEN").orNull ?: ""}\"")
        buildConfigField("long", "EXPORT_INTERVAL_MS", "${providers.gradleProperty("EXPORT_INTERVAL_MS").orNull ?: "200"}L")
        // SDK locations arrive about every 2 s. Expire outages, never renew on exporter ticks.
        // An explicit zero still builds a preview-only client.
        for ((budget, defaultMs) in mapOf("NAV_ASSIST_SOURCE_BUDGET_MS" to 3_000L, "NAV_ASSIST_PROGRESS_BUDGET_MS" to 6_000L)) {
            val value = providers.gradleProperty(budget).orNull?.toLongOrNull()?.coerceAtLeast(0L) ?: defaultMs
            buildConfigField("long", budget, "${value}L")
        }
        buildConfigField(
            "String",
            "NAV_ASSIST_V2_URL",
            (providers.gradleProperty("NAV_ASSIST_V2_URL").orNull ?: "").asBuildConfigString(),
        )
        buildConfigField(
            "long",
            "NAV_ASSIST_V2_INTERVAL_MS",
            "${navAssistV2IntervalMs}L",
        )
        buildConfigField("String", "HOME_ASSISTANT_URL", "\"${providers.gradleProperty("HOME_ASSISTANT_URL").orNull ?: ""}\"")
        buildConfigField("String", "HOME_ASSISTANT_TOKEN", "\"${providers.gradleProperty("HOME_ASSISTANT_TOKEN").orNull ?: ""}\"")
    }

    signingConfigs {
        create("laneTest") {
            storeFile = providers.gradleProperty("LANETEST_STORE_FILE").orNull?.let { file(it) }
            storePassword = providers.gradleProperty("LANETEST_STORE_PASSWORD").orNull
            keyAlias = "tesnavtest"
            keyPassword = providers.gradleProperty("LANETEST_STORE_PASSWORD").orNull
        }
    }

    buildTypes {
        create("tenengkai") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".tenengkai.lane"
            matchingFallbacks += listOf("debug")
            signingConfig = signingConfigs.getByName("laneTest")
            buildConfigField("boolean", "EXTENDED_NAV_SOURCES", "true")
            manifestPlaceholders["APP_NAME"] = "特会开·双相机测试R11"
            manifestPlaceholders["AMAP_API_KEY"] =
                providers.gradleProperty("LANETEST_AMAP_API_KEY").orNull
                    ?: providers.gradleProperty("TENENGKAI_AMAP_API_KEY").orNull
                    ?: providers.gradleProperty("AMAP_API_KEY").orNull
                    ?: ""
        }
        release {
            optimization {
                enable = false
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        buildConfig = true
    }
}

androidComponents.beforeVariants(androidComponents.selector().withBuildType("tenengkai")) {
    // Launching activities on a secondary display requires Android 8+.
    // Original TesNav retains Android 6 support.
    it.minSdk = 26
}

dependencies {
    implementation(libs.amap.navi)
    implementation(files(preparePhoneStereoCv))
    implementation(files("libs/onnxruntime-android-1.23.2.aar"))
    add("tenengkaiImplementation", "dev.rikka.shizuku:api:13.1.5")
    add("tenengkaiImplementation", "dev.rikka.shizuku:provider:13.1.5")
    add("tenengkaiImplementation", "org.lsposed.hiddenapibypass:hiddenapibypass:6.1")
    implementation(libs.androidx.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.gson)
    implementation(libs.okhttp)
    testImplementation(libs.junit)
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
