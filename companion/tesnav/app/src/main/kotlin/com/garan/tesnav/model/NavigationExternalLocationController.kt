package com.garan.tesnav.model

/** SDK boundary. Selection never changes NavigationState or route/control permission. */
internal interface NavigationExternalLocationSink {
    fun setExternalEnabled(enabled: Boolean)
    fun inject(fix: NavigationLocationObservation)
}

/** AMap's weak-signal callback describes phone satellites, not external vehicle GPS. */
internal fun selectedLocationWeak(external: Boolean, hasVehicleFix: Boolean, phoneWeak: Boolean): Boolean =
    if (external) !hasVehicleFix else phoneWeak

internal class NavigationExternalLocationController(private val sink: NavigationExternalLocationSink) {
    private val selector = NavigationLocationFallback()
    private var external = false
    val isExternalEnabled: Boolean get() = external
    var injectedFix: NavigationLocationObservation? = null
        private set

    fun update(phone: NavigationLocationObservation?, vehicle: NavigationLocationObservation?, active: Boolean,
               nowElapsedMs: Long, nowWallMs: Long, phoneSignalWeak: Boolean = false): NavigationLocationSelection {
        val selection = selector.select(phone.takeUnless { phoneSignalWeak }, vehicle, active, nowElapsedMs, nowWallMs)
        return try {
            if (selection.source == NavigationLocationSource.VEHICLE) {
                // Do not enable external mode without a new qualified measurement.
                if (!external && selection.vehicleFixToInject == null) {
                    return NavigationLocationSelection(NavigationLocationSource.NONE, reason = "awaitingNewVehicleFix")
                }
                selection.vehicleFixToInject?.let { fix ->
                    if (!external) {
                        // Set before the call so failure cleanup also covers partial SDK activation.
                        external = true
                        sink.setExternalEnabled(true)
                    }
                    sink.inject(fix)
                    injectedFix = fix
                }
            } else {
                disable()
            }
            selection
        } catch (_: Exception) {
            runCatching { disable() }
            injectedFix = null
            NavigationLocationSelection(NavigationLocationSource.NONE, reason = "sdkLocationError")
        }
    }

    private fun disable() {
        if (external) {
            sink.setExternalEnabled(false)
            external = false
        }
        injectedFix = null
    }

    fun reset() {
        // If disable throws, retain external=true so the next reset retries cleanup.
        try { disable() } finally { selector.reset(); injectedFix = null }
    }
}
