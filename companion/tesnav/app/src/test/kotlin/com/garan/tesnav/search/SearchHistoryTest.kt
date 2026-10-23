package com.garan.tesnav.search

import org.junit.Assert.*
import org.junit.Test

class SearchHistoryTest {
    @Test fun historyPersistsDeduplicatesAndMovesMostRecentToTop() {
        var stored: String? = null
        val history = SearchHistory({ stored }, { stored = it })
        history.recordQuery("  上海  ")
        history.recordQuery("苏州")
        history.recordQuery("上海")
        assertEquals(listOf("上海", "苏州"), SearchHistory({ stored }, {}).entries().map { it.query })
    }

    @Test fun selectedPlaceRetainsCoordinatesAndCanBeDeleted() {
        var stored: String? = null
        val history = SearchHistory({ stored }, { stored = it })
        val destination = AddressCandidate(31.2, 121.4, "上海市测试路", "测试地点", "poi-1")
        history.recordDestination(destination)
        assertEquals(destination, history.entries().single().destination)
        history.remove(history.entries().single())
        assertTrue(history.entries().isEmpty())
    }

    @Test fun historyIsBoundedAndClearDoesNotRestoreOldEntries() {
        var stored: String? = null
        val history = SearchHistory({ stored }, { stored = it })
        repeat(25) { history.recordQuery("地点$it") }
        assertEquals(20, history.entries().size)
        assertEquals("地点24", history.entries().first().query)
        history.clear()
        assertTrue(SearchHistory({ stored }, {}).entries().isEmpty())
    }

    @Test fun invalidHistoryDoesNotCrashAndBlankQueriesAreNotSaved() {
        var stored: String? = "{broken"
        val history = SearchHistory({ stored }, { stored = it })
        assertTrue(history.entries().isEmpty())
        history.recordQuery("   ")
        assertTrue(history.entries().isEmpty())
        history.recordQuery("正常地点")
        assertEquals("正常地点", history.entries().single().query)
    }
}
