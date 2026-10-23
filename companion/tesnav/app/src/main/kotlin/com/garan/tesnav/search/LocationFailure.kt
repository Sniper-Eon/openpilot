package com.garan.tesnav.search

data class LocationFailure(
    val errorCode: Int,
    val errorInfo: String,
)

fun selectLocationFailure(
    extrasErrorCode: Int,
    extrasErrorInfo: String?,
    subtypeErrorCode: Int,
    subtypeErrorInfo: String?,
): LocationFailure? {
    val errorCode = extrasErrorCode.takeIf { it != 0 }
        ?: subtypeErrorCode.takeIf { it != 0 }
        ?: return null
    val errorInfo = if (extrasErrorCode != 0) extrasErrorInfo else subtypeErrorInfo
    return LocationFailure(errorCode, errorInfo?.trim().orEmpty().ifBlank { "尚无有效定位" })
}
