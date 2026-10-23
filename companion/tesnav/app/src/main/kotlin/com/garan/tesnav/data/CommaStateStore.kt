package com.garan.tesnav.data

import com.garan.tesnav.model.CommaState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Keeps the latest Comma snapshot across WebSocket reconnects. */
class CommaStateStore {
    private val mutableState = MutableStateFlow(CommaState())
    val state: StateFlow<CommaState> = mutableState.asStateFlow()

    fun set(state: CommaState) {
        mutableState.value = state
    }
}
