package com.garan.tesnav.search

import android.content.Context
import com.google.gson.Gson
import java.util.Locale

data class SearchHistoryEntry(val query: String, val destination: AddressCandidate? = null) {
    val identity: String get() = destination?.let {
        "place:${it.poiId?.takeIf(String::isNotBlank) ?: "${it.latitude},${it.longitude}:${it.name}"}"
    } ?: "query:${query.lowercase(Locale.ROOT)}"
}

class SearchHistory(private val read: () -> String?, private val write: (String) -> Unit) {
    private val gson = Gson()
    fun entries(): List<SearchHistoryEntry> = runCatching {
        gson.fromJson(read(), Array<SearchHistoryEntry>::class.java).orEmpty()
            .filter { it.query.isNotBlank() && it.query.length <= 256 && (it.destination == null ||
                (it.destination.latitude.isFinite() && it.destination.longitude.isFinite() &&
                 it.destination.latitude in -90.0..90.0 && it.destination.longitude in -180.0..180.0)) }
            .distinctBy { it.identity }.take(20)
    }.getOrDefault(emptyList())

    fun recordQuery(query: String) = record(SearchHistoryEntry(query.trim()))
    fun recordDestination(destination: AddressCandidate) = record(SearchHistoryEntry(destination.name.trim(), destination))
    private fun record(entry: SearchHistoryEntry) {
        if (entry.query.isBlank() || entry.query.length > 256) return
        write(gson.toJson((listOf(entry) + entries().filterNot { it.identity == entry.identity }).take(20)))
    }
    fun remove(entry: SearchHistoryEntry) = write(gson.toJson(entries().filterNot { it.identity == entry.identity }))
    fun clear() = write("[]")

    companion object {
        fun from(context: Context): SearchHistory {
            val preferences = context.getSharedPreferences("search_history", Context.MODE_PRIVATE)
            return SearchHistory({ preferences.getString("entries_v1", null) }, {
                preferences.edit().putString("entries_v1", it).apply()
            })
        }
    }
}
