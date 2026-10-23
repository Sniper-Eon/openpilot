package com.garan.tesnav.search

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AddressLookupControllerTest {
    @Test
    fun `clearing input for history prevents an old explicit search from replacing history`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })
        controller.searchDestination("上海站")
        controller.suggestDestinations("", null)
        gateway.destinationRequests.single().complete(
            LookupResult.Success(listOf(suggestion("旧结果", 31.2, 121.4))),
        )
        assertTrue(view.suggestionBatches.last().isEmpty())
    }

    @Test
    fun `blank submission invalidates an older destination result`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })

        controller.searchDestination("北京南站")
        controller.searchDestination("  ")
        gateway.destinationRequests.single().complete(
            LookupResult.Success(listOf(suggestion("北京南站", 39.865, 116.379))),
        )

        assertTrue(view.destinations.isEmpty())
        assertEquals(listOf("请输入目的地地址"), view.destinationErrors)
    }

    @Test
    fun `closing screen prevents late search callbacks from updating the view`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })

        controller.searchDestination("上海南站")
        controller.updateLocation(AddressPoint(31.2304, 121.4737))
        controller.close()
        gateway.destinationRequests.single().complete(
            LookupResult.Success(listOf(suggestion("上海南站", 31.154, 121.429))),
        )
        gateway.reverseRequests.single().complete(LookupResult.Success("上海市黄浦区"))

        assertTrue(gateway.closed)
        assertTrue(view.destinations.isEmpty())
        assertTrue(view.currentAddresses.isEmpty())
    }

    @Test
    fun `location failure invalidates an older reverse geocode callback`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })

        controller.updateLocation(AddressPoint(31.2304, 121.4737))
        controller.locationFailed("尚无有效定位")
        gateway.reverseRequests.single().complete(LookupResult.Success("不应显示的旧地址"))

        assertEquals(listOf("尚无有效定位"), view.currentAddressErrors)
        assertTrue(view.currentAddresses.isEmpty())
    }

    @Test
    fun `failed current address lookup releases in-flight request for a later retry`() {
        var nowMs = 1_000L
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { nowMs })
        val point = AddressPoint(31.2304, 121.4737)

        controller.updateLocation(point)
        controller.updateLocation(AddressPoint(31.2404, 121.4737))
        assertEquals(1, gateway.reverseRequests.size)

        gateway.reverseRequests.single().complete(LookupResult.Failure("当前地址解析失败（网络异常）"))
        nowMs = 16_000L
        controller.updateLocation(point)

        assertEquals(2, gateway.reverseRequests.size)
        assertEquals(listOf("当前地址解析失败（网络异常）"), view.currentAddressErrors)
    }

    @Test
    fun `current address lookup is rate limited and deduplicated by movement`() {
        var nowMs = 1_000L
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { nowMs })
        val firstPoint = AddressPoint(31.2304, 121.4737)

        controller.updateLocation(firstPoint)
        assertEquals(1, gateway.reverseRequests.size)
        gateway.reverseRequests.single().complete(LookupResult.Success("上海市黄浦区"))

        nowMs = 2_000L
        controller.updateLocation(AddressPoint(31.2314, 121.4737))
        assertEquals(1, gateway.reverseRequests.size)

        nowMs = 17_000L
        controller.updateLocation(AddressPoint(31.23045, 121.4737))
        assertEquals(1, gateway.reverseRequests.size)

        controller.updateLocation(AddressPoint(31.2314, 121.4737))
        assertEquals(2, gateway.reverseRequests.size)

        assertEquals(listOf("上海市黄浦区"), view.currentAddresses)
        assertEquals(2, view.currentAddressLoadingCount)
    }

    @Test
    fun `blank destination address fails without calling the search service`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })

        controller.searchDestination("   ")

        assertTrue(gateway.destinationRequests.isEmpty())
        assertEquals(listOf("请输入目的地地址"), view.destinationErrors)
    }

    @Test
    fun `latest destination search returns choices without auto selecting one`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })

        controller.searchDestination("  北京南站  ")
        controller.searchDestination("北京西站")

        gateway.destinationRequests[0].complete(
            LookupResult.Success(listOf(suggestion("北京南站", 39.865, 116.379))),
        )
        assertTrue(view.destinations.isEmpty())

        gateway.destinationRequests[1].complete(
            LookupResult.Success(listOf(
                suggestion("北京西站", 39.895, 116.322),
                suggestion("北京西站北广场", 39.896, 116.323),
            )),
        )

        assertEquals(listOf("北京南站", "北京西站"), gateway.destinationRequests.map { it.query })
        assertEquals(listOf("北京西站", "北京西站北广场"), view.suggestionBatches.last().map { it.name })
        assertTrue(view.destinations.isEmpty())
    }

    @Test
    fun `selecting one suggestion resolves only that destination`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })
        val selected = suggestion("上海虹桥站", 31.197, 121.327)

        controller.selectSuggestion(selected)
        gateway.resolveRequests.single().complete(
            LookupResult.Success(AddressCandidate(31.197, 121.327, "上海市闵行区上海虹桥站", "上海虹桥站", "poi-1")),
        )

        assertEquals("上海虹桥站", gateway.resolveRequests.single().suggestion.name)
        assertEquals("上海虹桥站", view.destinations.single().name)
    }

    @Test
    fun `new suggestion query invalidates an older callback`() {
        val gateway = FakeAddressLookupGateway()
        val view = RecordingAddressLookupView()
        val controller = AddressLookupController(gateway, view, elapsedRealtimeMs = { 1_000L })

        controller.suggestDestinations("虹桥", null)
        controller.suggestDestinations("虹桥站", null)
        gateway.suggestionRequests[0].complete(LookupResult.Success(listOf(suggestion("旧结果", 1.0, 1.0))))
        gateway.suggestionRequests[1].complete(LookupResult.Success(listOf(suggestion("上海虹桥站", 31.197, 121.327))))

        assertEquals(listOf("上海虹桥站"), view.suggestionBatches.last().map { it.name })
    }

    private class FakeAddressLookupGateway : AddressLookupGateway {
        val destinationRequests = mutableListOf<DestinationRequest>()
        val suggestionRequests = mutableListOf<DestinationRequest>()
        val resolveRequests = mutableListOf<ResolveRequest>()
        val reverseRequests = mutableListOf<ReverseRequest>()
        var closed = false

        override fun suggestDestinations(
            query: String,
            near: AddressPoint?,
            callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
        ) {
            suggestionRequests += DestinationRequest(query, callback)
        }

        override fun searchDestinations(
            query: String,
            near: AddressPoint?,
            callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
        ) {
            destinationRequests += DestinationRequest(query, callback)
        }

        override fun resolveSuggestion(
            suggestion: AddressSuggestion,
            callback: (LookupResult<AddressCandidate>) -> Unit,
        ) {
            resolveRequests += ResolveRequest(suggestion, callback)
        }

        override fun reverseGeocode(
            point: AddressPoint,
            callback: (LookupResult<String>) -> Unit,
        ) {
            reverseRequests += ReverseRequest(point, callback)
        }

        override fun close() {
            closed = true
        }
    }

    private data class DestinationRequest(
        val query: String,
        val callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
    ) {
        fun complete(result: LookupResult<List<AddressSuggestion>>) = callback(result)
    }

    private data class ResolveRequest(
        val suggestion: AddressSuggestion,
        val callback: (LookupResult<AddressCandidate>) -> Unit,
    ) {
        fun complete(result: LookupResult<AddressCandidate>) = callback(result)
    }

    private data class ReverseRequest(
        val point: AddressPoint,
        val callback: (LookupResult<String>) -> Unit,
    ) {
        fun complete(result: LookupResult<String>) = callback(result)
    }

    private class RecordingAddressLookupView : AddressLookupView {
        val destinations = mutableListOf<AddressCandidate>()
        val suggestionBatches = mutableListOf<List<AddressSuggestion>>()
        val destinationErrors = mutableListOf<String>()
        val currentAddresses = mutableListOf<String>()
        val currentAddressErrors = mutableListOf<String>()
        var currentAddressLoadingCount = 0

        override fun onDestinationSearchStarted(query: String) = Unit
        override fun onDestinationSuggestions(suggestions: List<AddressSuggestion>) {
            suggestionBatches += suggestions
        }
        override fun onDestinationFound(candidate: AddressCandidate) {
            destinations += candidate
        }
        override fun onDestinationSearchFailed(message: String) {
            destinationErrors += message
        }
        override fun onCurrentAddressLoading() {
            currentAddressLoadingCount++
        }
        override fun onCurrentAddressResolved(address: String) {
            currentAddresses += address
        }
        override fun onCurrentAddressFailed(message: String) {
            currentAddressErrors += message
        }
    }

    private companion object {
        fun suggestion(name: String, latitude: Double, longitude: Double) = AddressSuggestion(
            stableId = name,
            poiId = "poi-$name",
            name = name,
            district = "",
            address = name,
            point = AddressPoint(latitude, longitude),
        )
    }
}
