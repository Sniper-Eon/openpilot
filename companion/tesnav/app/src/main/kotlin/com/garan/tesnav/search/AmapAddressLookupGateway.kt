package com.garan.tesnav.search

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.amap.api.services.core.AMapException
import com.amap.api.services.core.LatLonPoint
import com.amap.api.services.core.PoiItemV2
import com.amap.api.services.geocoder.GeocodeQuery
import com.amap.api.services.geocoder.GeocodeResult
import com.amap.api.services.geocoder.GeocodeSearch
import com.amap.api.services.geocoder.RegeocodeQuery
import com.amap.api.services.geocoder.RegeocodeResult
import com.amap.api.services.help.Inputtips
import com.amap.api.services.help.InputtipsQuery
import com.amap.api.services.help.Tip
import com.amap.api.services.poisearch.PoiResultV2
import com.amap.api.services.poisearch.PoiSearchV2
import com.amap.api.services.poisearch.VisualSearchResult

/** Thin lifecycle-safe adapter around the Search SDK already bundled with the navigation SDK. */
class AmapAddressLookupGateway(context: Context) : AddressLookupGateway {
    private val applicationContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val lock = Any()
    private val activeGeocoders = mutableSetOf<GeocodeSearch>()
    private val activeInputtips = mutableSetOf<Inputtips>()
    private val activePoiSearches = mutableSetOf<PoiSearchV2>()

    @Volatile
    private var closed = false

    override fun suggestDestinations(
        query: String,
        near: AddressPoint?,
        callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
    ) {
        val inputtips = createInputtips(
            InputtipsQuery(query, "").apply {
                near?.let { location = LatLonPoint(it.latitude, it.longitude) }
            },
        ) { callback(LookupResult.Failure("目的地提示失败：$it")) } ?: return
        inputtips.setInputtipsListener { tips, errorCode ->
            val result = if (errorCode == AMapException.CODE_AMAP_SUCCESS) {
                LookupResult.Success(tips.orEmpty().mapNotNull(::tipSuggestion))
            } else {
                LookupResult.Failure("目的地提示失败：${AmapSearchErrorMessage.forCode(errorCode)}")
            }
            finish(inputtips) { callback(result) }
        }
        runCatching { inputtips.requestInputtipsAsyn() }
            .onFailure { error ->
                finish(inputtips) {
                    callback(LookupResult.Failure("目的地提示失败：${error.message ?: "无法启动地点提示"}"))
                }
            }
    }

    override fun searchDestinations(
        query: String,
        near: AddressPoint?,
        callback: (LookupResult<List<AddressSuggestion>>) -> Unit,
    ) {
        val searchQuery = PoiSearchV2.Query(query, "").apply {
            pageNum = 0
            pageSize = MAX_POI_RESULTS
            showFields = PoiSearchV2.ShowFields(PoiSearchV2.ShowFields.NAVI)
            near?.let {
                location = LatLonPoint(it.latitude, it.longitude)
                isDistanceSort = true
            }
        }
        val search = createPoiSearch(searchQuery) { callback(LookupResult.Failure("目的地搜索失败：$it")) } ?: return
        search.setOnPoiSearchListener(object : PoiSearchV2.OnPoiSearchListener {
            override fun onPoiSearched(result: PoiResultV2?, errorCode: Int) {
                val lookupResult = if (errorCode == AMapException.CODE_AMAP_SUCCESS) {
                    LookupResult.Success(result?.pois.orEmpty().mapNotNull(::poiSuggestion))
                } else {
                    LookupResult.Failure("目的地搜索失败：${AmapSearchErrorMessage.forCode(errorCode)}")
                }
                finish(search) { callback(lookupResult) }
            }

            override fun onPoiItemSearched(item: PoiItemV2?, errorCode: Int) = Unit
            override fun onVisualSearched(result: VisualSearchResult?, errorCode: Int) = Unit
        })
        runCatching { search.searchPOIAsyn() }
            .onFailure { error ->
                finish(search) {
                    callback(LookupResult.Failure("目的地搜索失败：${error.message ?: "无法启动地点搜索"}"))
                }
            }
    }

    override fun resolveSuggestion(
        suggestion: AddressSuggestion,
        callback: (LookupResult<AddressCandidate>) -> Unit,
    ) {
        suggestion.point?.takeIf { it.isValid() }?.let { point ->
            deliver { callback(LookupResult.Success(suggestion.toCandidate(point))) }
            return
        }
        val poiId = suggestion.poiId?.takeIf(String::isNotBlank)
        if (poiId != null) {
            resolvePoiId(suggestion, poiId, callback)
        } else {
            resolveWithGeocoder(suggestion, callback)
        }
    }

    private fun resolvePoiId(
        suggestion: AddressSuggestion,
        poiId: String,
        callback: (LookupResult<AddressCandidate>) -> Unit,
    ) {
        val search = createPoiSearch(PoiSearchV2.Query(suggestion.name, "")) {
            callback(LookupResult.Failure("目的地解析失败：$it"))
        } ?: return
        search.setOnPoiSearchListener(object : PoiSearchV2.OnPoiSearchListener {
            override fun onPoiSearched(result: PoiResultV2?, errorCode: Int) = Unit

            override fun onPoiItemSearched(item: PoiItemV2?, errorCode: Int) {
                val result = if (errorCode == AMapException.CODE_AMAP_SUCCESS) {
                    item?.let(::poiCandidate)
                        ?.let { LookupResult.Success(it) }
                        ?: LookupResult.Failure("目的地解析失败：高德未返回可导航坐标")
                } else {
                    LookupResult.Failure("目的地解析失败：${AmapSearchErrorMessage.forCode(errorCode)}")
                }
                finish(search) { callback(result) }
            }

            override fun onVisualSearched(result: VisualSearchResult?, errorCode: Int) = Unit
        })
        runCatching { search.searchPOIIdAsyn(poiId) }
            .onFailure { error ->
                finish(search) {
                    callback(LookupResult.Failure("目的地解析失败：${error.message ?: "无法查询 POI"}"))
                }
            }
    }

    private fun resolveWithGeocoder(
        suggestion: AddressSuggestion,
        callback: (LookupResult<AddressCandidate>) -> Unit,
    ) {
        val search = createGeocoder { callback(LookupResult.Failure("目的地解析失败：$it")) } ?: return
        search.setOnGeocodeSearchListener(object : GeocodeSearch.OnGeocodeSearchListener {
            override fun onGeocodeSearched(result: GeocodeResult?, errorCode: Int) {
                val lookupResult: LookupResult<AddressCandidate> = if (errorCode == AMapException.CODE_AMAP_SUCCESS) {
                    val address = result?.geocodeAddressList.orEmpty().firstOrNull { it?.latLonPoint != null }
                    val point = address?.latLonPoint
                    if (point != null) {
                        LookupResult.Success(AddressCandidate(
                            latitude = point.latitude,
                            longitude = point.longitude,
                            formattedAddress = address.formatAddress?.trim().orEmpty().ifBlank { suggestion.displayAddress() },
                            name = suggestion.name,
                            poiId = suggestion.poiId,
                        ))
                    } else {
                        LookupResult.Failure("目的地解析失败：高德未返回可导航坐标")
                    }
                } else {
                    LookupResult.Failure("目的地解析失败：${AmapSearchErrorMessage.forCode(errorCode)}")
                }
                finish(search) { callback(lookupResult) }
            }

            override fun onRegeocodeSearched(result: RegeocodeResult?, errorCode: Int) = Unit
        })
        runCatching { search.getFromLocationNameAsyn(GeocodeQuery(suggestion.displayAddress(), "")) }
            .onFailure { error ->
                finish(search) {
                    callback(LookupResult.Failure("目的地解析失败：${error.message ?: "无法启动地址搜索"}"))
                }
            }
    }

    override fun reverseGeocode(
        point: AddressPoint,
        callback: (LookupResult<String>) -> Unit,
    ) {
        val search = createGeocoder { callback(LookupResult.Failure("当前地址解析失败：$it")) } ?: return
        search.setOnGeocodeSearchListener(object : GeocodeSearch.OnGeocodeSearchListener {
            override fun onGeocodeSearched(result: GeocodeResult?, errorCode: Int) = Unit

            override fun onRegeocodeSearched(result: RegeocodeResult?, errorCode: Int) {
                val lookupResult = if (errorCode == AMapException.CODE_AMAP_SUCCESS) {
                    result?.regeocodeAddress?.formatAddress
                        ?.trim()
                        ?.takeIf(String::isNotEmpty)
                        ?.let { LookupResult.Success(it) }
                        ?: LookupResult.Failure("当前地址解析失败：高德未返回地址")
                } else {
                    LookupResult.Failure("当前地址解析失败：${AmapSearchErrorMessage.forCode(errorCode)}")
                }
                finish(search) { callback(lookupResult) }
            }
        })
        runCatching {
            search.getFromLocationAsyn(
                RegeocodeQuery(
                    LatLonPoint(point.latitude, point.longitude),
                    REVERSE_RADIUS_METERS,
                    GeocodeSearch.AMAP,
                ),
            )
        }.onFailure { error ->
            finish(search) {
                callback(LookupResult.Failure("当前地址解析失败：${error.message ?: "无法启动地址解析"}"))
            }
        }
    }

    override fun close() {
        val resources = synchronized(lock) {
            if (closed) return
            closed = true
            Triple(activeGeocoders.toList(), activeInputtips.toList(), activePoiSearches.toList()).also {
                activeGeocoders.clear()
                activeInputtips.clear()
                activePoiSearches.clear()
            }
        }
        resources.first.forEach { it.setOnGeocodeSearchListener(null) }
        resources.second.forEach { it.setInputtipsListener(null) }
        resources.third.forEach { it.setOnPoiSearchListener(null) }
        mainHandler.removeCallbacksAndMessages(null)
    }

    private fun createGeocoder(onFailure: (String) -> Unit): GeocodeSearch? {
        if (closed) return null
        val search = try {
            GeocodeSearch(applicationContext)
        } catch (error: AMapException) {
            deliver { onFailure(AmapSearchErrorMessage.forCode(error.errorCode)) }
            return null
        } catch (error: RuntimeException) {
            deliver { onFailure(error.message ?: "高德地址服务初始化失败") }
            return null
        }
        synchronized(lock) {
            if (closed) {
                search.setOnGeocodeSearchListener(null)
                return null
            }
            activeGeocoders += search
        }
        return search
    }

    private fun finish(search: GeocodeSearch, callback: () -> Unit) {
        search.setOnGeocodeSearchListener(null)
        synchronized(lock) { activeGeocoders -= search }
        deliver(callback)
    }

    private fun createInputtips(query: InputtipsQuery, onFailure: (String) -> Unit): Inputtips? =
        createResource(onFailure, { Inputtips(applicationContext, query) }) { activeInputtips += it }

    private fun createPoiSearch(query: PoiSearchV2.Query, onFailure: (String) -> Unit): PoiSearchV2? =
        createResource(onFailure, { PoiSearchV2(applicationContext, query) }) { activePoiSearches += it }

    private fun <T> createResource(onFailure: (String) -> Unit, create: () -> T, register: (T) -> Unit): T? {
        if (closed) return null
        val resource = try {
            create()
        } catch (error: AMapException) {
            deliver { onFailure(AmapSearchErrorMessage.forCode(error.errorCode)) }
            return null
        } catch (error: RuntimeException) {
            deliver { onFailure(error.message ?: "高德搜索服务初始化失败") }
            return null
        }
        synchronized(lock) {
            if (closed) return null
            register(resource)
        }
        return resource
    }

    private fun finish(inputtips: Inputtips, callback: () -> Unit) {
        inputtips.setInputtipsListener(null)
        synchronized(lock) { activeInputtips -= inputtips }
        deliver(callback)
    }

    private fun finish(search: PoiSearchV2, callback: () -> Unit) {
        search.setOnPoiSearchListener(null)
        synchronized(lock) { activePoiSearches -= search }
        deliver(callback)
    }

    private fun tipSuggestion(tip: Tip?): AddressSuggestion? {
        val name = tip?.name?.trim().orEmpty()
        if (name.isEmpty()) return null
        val point = tip?.point?.let { AddressPoint(it.latitude, it.longitude) }?.takeIf { it.isValid() }
        val poiId = tip?.poiID?.trim()?.takeIf(String::isNotEmpty)
        val district = tip?.district?.trim().orEmpty()
        val address = tip?.address?.trim().orEmpty()
        return AddressSuggestion(stableId(poiId, name, district, address, point), poiId, name, district, address, point)
    }

    private fun poiSuggestion(item: PoiItemV2?): AddressSuggestion? {
        val candidate = item?.let(::poiCandidate) ?: return null
        val point = AddressPoint(candidate.latitude, candidate.longitude)
        val district = listOfNotNull(item.provinceName, item.cityName, item.adName)
            .map(String::trim).filter(String::isNotEmpty).distinct().joinToString()
        val address = item.snippet?.trim().orEmpty()
        return AddressSuggestion(
            stableId(candidate.poiId, candidate.name, district, address, point),
            candidate.poiId,
            candidate.name,
            district,
            address,
            point,
        )
    }

    private fun poiCandidate(item: PoiItemV2): AddressCandidate? {
        val point = item.poiNavi?.enter ?: item.latLonPoint ?: return null
        val name = item.title?.trim().orEmpty()
        if (name.isEmpty()) return null
        val district = listOfNotNull(item.provinceName, item.cityName, item.adName)
            .map(String::trim).filter(String::isNotEmpty).distinct().joinToString()
        val address = item.snippet?.trim().orEmpty()
        return AddressCandidate(
            latitude = point.latitude,
            longitude = point.longitude,
            formattedAddress = listOf(district, address, name).filter(String::isNotBlank).distinct().joinToString(" "),
            name = name,
            poiId = item.poiId?.trim()?.takeIf(String::isNotEmpty),
        )
    }

    private fun AddressSuggestion.toCandidate(point: AddressPoint) = AddressCandidate(
        latitude = point.latitude,
        longitude = point.longitude,
        formattedAddress = displayAddress(),
        name = name,
        poiId = poiId,
    )

    private fun AddressSuggestion.displayAddress(): String =
        listOf(district, address, name).filter(String::isNotBlank).distinct().joinToString(" ")

    private fun stableId(poiId: String?, name: String, district: String, address: String, point: AddressPoint?): String =
        poiId ?: listOf(name, district, address, point?.latitude, point?.longitude).joinToString("|")

    private fun AddressPoint.isValid(): Boolean =
        latitude.isFinite() && longitude.isFinite() && latitude in -90.0..90.0 && longitude in -180.0..180.0

    private fun deliver(callback: () -> Unit) {
        val guarded = Runnable { if (!closed) callback() }
        if (Looper.myLooper() == Looper.getMainLooper()) guarded.run() else mainHandler.post(guarded)
    }

    private companion object {
        const val REVERSE_RADIUS_METERS = 200f
        const val MAX_POI_RESULTS = 10
    }
}

internal object AmapSearchErrorMessage {
    fun forCode(errorCode: Int): String = when (errorCode) {
        1002, 1008, 1009 -> "高德 API Key、签名或平台配置错误（$errorCode）"
        1005 -> "高德地址服务请求过于频繁（$errorCode）"
        1802, 1804, 1806 -> "高德地址服务网络异常（$errorCode）"
        1200, 1901 -> "地址查询参数无效（$errorCode）"
        else -> "高德地址服务失败（$errorCode）"
    }
}
