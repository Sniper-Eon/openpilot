package com.garan.tesnav.data

import com.google.gson.JsonElement
import com.google.gson.JsonParser

internal fun structuredTrafficLightCountdown(raw: String?): Int? {
    if (raw.isNullOrBlank()) return null
    val root = runCatching { JsonParser.parseString(raw) }.getOrNull() ?: return null
    return findTrafficLightCountdown(root, false)
}

private fun findTrafficLightCountdown(element: JsonElement, insideTrafficLight: Boolean): Int? = when {
    element.isJsonArray -> element.asJsonArray.firstNotNullOfOrNull { findTrafficLightCountdown(it, insideTrafficLight) }
    element.isJsonObject -> {
        val entries = element.asJsonObject.entrySet()
        entries.firstNotNullOfOrNull { (key, value) ->
            val normalized = key.filter(Char::isLetterOrDigit).lowercase()
            val isCountdown = normalized == "trafficlightcountdown" ||
                insideTrafficLight && normalized in setOf("countdown", "countdownsecond", "countdownseconds")
            value.intOrNull()?.takeIf { isCountdown && it in 0..3_600 }
        } ?: entries.firstNotNullOfOrNull { (key, value) ->
            val normalized = key.filter(Char::isLetterOrDigit).lowercase()
            findTrafficLightCountdown(value, insideTrafficLight || "trafficlight" in normalized)
        }
    }
    else -> null
}

private fun JsonElement.intOrNull(): Int? = takeIf { it.isJsonPrimitive }?.asJsonPrimitive?.let { primitive ->
    runCatching { primitive.asInt }.getOrNull()
}
