package com.garan.tesnav.data

import com.garan.tesnav.model.NavigationState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Thread-safe pool containing only the newest complete navigation snapshot. */
class NavigationStateStore {
    private val mutableState = MutableStateFlow(NavigationState())
    val state: StateFlow<NavigationState> = mutableState.asStateFlow()

    @Synchronized
    fun update(transform: NavigationState.() -> NavigationState) {
        mutableState.value = mutableState.value.transform().copy(timestamp = System.currentTimeMillis())
    }
}
