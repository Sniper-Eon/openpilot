package com.garan.tesnav.search

data class AddressPoint(
    val latitude: Double,
    val longitude: Double,
)

data class AddressCandidate(
    val latitude: Double,
    val longitude: Double,
    val formattedAddress: String,
    val name: String = formattedAddress,
    val poiId: String? = null,
)

data class AddressSuggestion(
    val stableId: String,
    val poiId: String?,
    val name: String,
    val district: String,
    val address: String,
    val point: AddressPoint?,
)

sealed interface LookupResult<out T> {
    data class Success<T>(val value: T) : LookupResult<T>
    data class Failure(val message: String) : LookupResult<Nothing>
}

interface AddressLookupGateway {
    fun suggestDestinations(
        query: String,
        near: AddressPoint?,
        callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
    )

    fun searchDestinations(
        query: String,
        near: AddressPoint?,
        callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
    )

    fun resolveSuggestion(
        suggestion: AddressSuggestion,
        callback: (LookupResult<AddressCandidate>) -> Unit,
    )

    fun reverseGeocode(
        point: AddressPoint,
        callback: (LookupResult<String>) -> Unit,
    )

    fun close()
}

interface AddressLookupView {
    fun onDestinationSearchStarted(query: String)
    fun onDestinationSuggestions(suggestions: List<AddressSuggestion>)
    fun onDestinationFound(candidate: AddressCandidate)
    fun onDestinationSearchFailed(message: String)
    fun onCurrentAddressLoading()
    fun onCurrentAddressResolved(address: String)
    fun onCurrentAddressFailed(message: String)
}

class AddressLookupController(
    private val gateway: AddressLookupGateway,
    private val view: AddressLookupView,
    private val elapsedRealtimeMs: () -> Long,
) {
    private var active = true
    private var destinationGeneration = 0L
    private var suggestionGeneration = 0L
    private var reverseGeneration = 0L
    private var reverseInFlight = false
    private var lastReverseAttemptAtMs: Long? = null
    private var lastResolvedPoint: AddressPoint? = null

    fun suggestDestinations(rawQuery: String, near: AddressPoint?) {
        if (!active) return
        destinationGeneration++
        val query = rawQuery.trim()
        val generation = ++suggestionGeneration
        if (query.length < MIN_SUGGESTION_QUERY_LENGTH) {
            view.onDestinationSuggestions(emptyList())
            return
        }
        gateway.suggestDestinations(query, near) { result ->
            if (!active || generation != suggestionGeneration) return@suggestDestinations
            when (result) {
                is LookupResult.Success -> view.onDestinationSuggestions(validSuggestions(result.value))
                is LookupResult.Failure -> view.onDestinationSuggestions(emptyList())
            }
        }
    }

    fun searchDestination(rawQuery: String, near: AddressPoint? = null) {
        if (!active) return
        val query = rawQuery.trim()
        val generation = ++destinationGeneration
        suggestionGeneration++
        if (query.isEmpty()) {
            view.onDestinationSuggestions(emptyList())
            view.onDestinationSearchFailed(DESTINATION_REQUIRED)
            return
        }
        view.onDestinationSuggestions(emptyList())
        view.onDestinationSearchStarted(query)
        gateway.searchDestinations(query, near) { result ->
            if (!active || generation != destinationGeneration) return@searchDestinations
            when (result) {
                is LookupResult.Success -> validSuggestions(result.value).takeIf { it.isNotEmpty() }
                    ?.let(view::onDestinationSuggestions)
                    ?: view.onDestinationSearchFailed(DESTINATION_NOT_FOUND)
                is LookupResult.Failure -> view.onDestinationSearchFailed(result.message)
            }
        }
    }

    fun selectSuggestion(suggestion: AddressSuggestion) {
        if (!active) return
        val generation = ++destinationGeneration
        suggestionGeneration++
        view.onDestinationSuggestions(emptyList())
        view.onDestinationSearchStarted(suggestion.name)
        gateway.resolveSuggestion(suggestion) { result ->
            if (!active || generation != destinationGeneration) return@resolveSuggestion
            when (result) {
                is LookupResult.Success -> result.value.takeIf(::isValidCandidate)
                    ?.let(view::onDestinationFound)
                    ?: view.onDestinationSearchFailed(DESTINATION_NOT_FOUND)
                is LookupResult.Failure -> view.onDestinationSearchFailed(result.message)
            }
        }
    }

    fun updateLocation(point: AddressPoint) {
        if (!active) return
        if (!point.isValid()) {
            view.onCurrentAddressFailed(CURRENT_LOCATION_INVALID)
            return
        }
        if (reverseInFlight) return

        val nowMs = elapsedRealtimeMs()
        if (lastResolvedPoint?.let { distanceMeters(it, point) < MIN_REVERSE_DISTANCE_METERS } == true) return
        if (lastReverseAttemptAtMs?.let { nowMs - it < MIN_REVERSE_INTERVAL_MS } == true) return

        lastReverseAttemptAtMs = nowMs
        reverseInFlight = true
        val generation = ++reverseGeneration
        view.onCurrentAddressLoading()
        gateway.reverseGeocode(point) { result ->
            if (!active || generation != reverseGeneration) return@reverseGeocode
            reverseInFlight = false
            when (result) {
                is LookupResult.Success -> {
                    val address = result.value.trim()
                    if (address.isEmpty()) {
                        lastResolvedPoint = null
                        view.onCurrentAddressFailed(CURRENT_ADDRESS_UNAVAILABLE)
                    } else {
                        lastResolvedPoint = point
                        view.onCurrentAddressResolved(address)
                    }
                }
                is LookupResult.Failure -> {
                    lastResolvedPoint = null
                    view.onCurrentAddressFailed(result.message)
                }
            }
        }
    }

    fun locationFailed(message: String) {
        if (!active) return
        reverseGeneration++
        reverseInFlight = false
        lastReverseAttemptAtMs = null
        lastResolvedPoint = null
        view.onCurrentAddressFailed(message.ifBlank { CURRENT_LOCATION_UNAVAILABLE })
    }

    fun close() {
        if (!active) return
        active = false
        destinationGeneration++
        suggestionGeneration++
        reverseGeneration++
        reverseInFlight = false
        gateway.close()
    }

    private fun isValidCandidate(candidate: AddressCandidate): Boolean =
        candidate.latitude in -90.0..90.0 &&
            candidate.longitude in -180.0..180.0 &&
            candidate.formattedAddress.isNotBlank()

    private fun validSuggestions(suggestions: List<AddressSuggestion>): List<AddressSuggestion> =
        suggestions.asSequence()
            .filter { suggestion ->
                suggestion.name.isNotBlank() &&
                    (suggestion.point?.let { it.isValid() } == true || !suggestion.poiId.isNullOrBlank() || suggestion.address.isNotBlank())
            }
            .distinctBy(AddressSuggestion::stableId)
            .take(MAX_SUGGESTIONS)
            .toList()

    private fun AddressPoint.isValid(): Boolean =
        latitude.isFinite() && longitude.isFinite() &&
            latitude in -90.0..90.0 && longitude in -180.0..180.0

    private fun distanceMeters(first: AddressPoint, second: AddressPoint): Double {
        val firstLat = Math.toRadians(first.latitude)
        val secondLat = Math.toRadians(second.latitude)
        val deltaLat = secondLat - firstLat
        val deltaLon = Math.toRadians(second.longitude - first.longitude)
        val haversine = kotlin.math.sin(deltaLat / 2).let { it * it } +
            kotlin.math.cos(firstLat) * kotlin.math.cos(secondLat) *
            kotlin.math.sin(deltaLon / 2).let { it * it }
        return EARTH_RADIUS_METERS * 2 * kotlin.math.asin(kotlin.math.sqrt(haversine.coerceIn(0.0, 1.0)))
    }

    private companion object {
        const val MIN_REVERSE_INTERVAL_MS = 15_000L
        const val MIN_REVERSE_DISTANCE_METERS = 50.0
        const val EARTH_RADIUS_METERS = 6_371_000.0
        const val MIN_SUGGESTION_QUERY_LENGTH = 2
        const val MAX_SUGGESTIONS = 8
        const val DESTINATION_REQUIRED = "请输入目的地地址"
        const val DESTINATION_NOT_FOUND = "未找到可导航的目的地"
        const val CURRENT_LOCATION_INVALID = "定位坐标无效"
        const val CURRENT_LOCATION_UNAVAILABLE = "尚无有效定位"
        const val CURRENT_ADDRESS_UNAVAILABLE = "当前位置地址暂不可用"
    }
}
