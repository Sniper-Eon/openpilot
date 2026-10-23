package com.garan.tesnav.service

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import com.garan.tesnav.export.LaneAnnouncement
import java.util.Locale

/** Android TTS provides request IDs and done/error/stop, unlike AMap's text-only callbacks. */
internal class LaneChangeSpeech(context: Context, private val enabled: () -> Boolean,
                                private val completed: (String, String) -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val tracker = LaneAnnouncementTracker()
    private var ready = false
    private var closed = false
    private val expiry = Runnable { cancel() }
    private val focus = AudioManager.OnAudioFocusChangeListener { change ->
        if (change < 0) main.post { cancel() }
    }
    private var tts: TextToSpeech? = null

    init {
        tts = TextToSpeech(context.applicationContext) { status ->
            main.post {
                if (!closed && status == TextToSpeech.SUCCESS) {
                    val language = tts?.setLanguage(Locale.SIMPLIFIED_CHINESE) ?: TextToSpeech.LANG_NOT_SUPPORTED
                    ready = language >= TextToSpeech.LANG_AVAILABLE
                    tts?.setAudioAttributes(AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                }
            }
        }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String) { main.post {
                if (audible()) tracker.onStart(id, SystemClock.elapsedRealtime()) else cancel()
            } }
            override fun onDone(id: String) { main.post {
                tracker.onDone(id, audible(), SystemClock.elapsedRealtime())?.let {
                    completed(it.id, it.sessionId)
                    abandonFocus()
                }
            } }
            @Deprecated("Android callback")
            override fun onError(id: String) { failed(id) }
            override fun onError(id: String, errorCode: Int) { failed(id) }
            override fun onStop(id: String, interrupted: Boolean) { failed(id) }
        })
    }

    private fun audible() = !closed && ready && enabled() &&
        audio.getStreamVolume(AudioManager.STREAM_MUSIC) > 0 && !audio.isStreamMute(AudioManager.STREAM_MUSIC)

    @Suppress("DEPRECATION")
    fun offer(request: LaneAnnouncement?) {
        val old = tracker.pending?.id
        val text = tracker.offer(request, audible(), SystemClock.elapsedRealtime())
        main.removeCallbacks(expiry)
        if (tracker.pending == null) {
            if (old != null) { tts?.stop(); abandonFocus() }
            return
        }
        main.postDelayed(expiry, 1_000L)
        if (text == null) return
        if (audio.requestAudioFocus(focus, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) { cancel(); return }
        val id = tracker.pending?.id ?: return
        if (tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) cancel()
    }

    private fun failed(id: String) { main.post { if (tracker.pending?.id == id) cancel() } }
    @Suppress("DEPRECATION")
    private fun abandonFocus() { audio.abandonAudioFocus(focus) }
    fun cancel() { tracker.cancel(); main.removeCallbacks(expiry); tts?.stop(); abandonFocus() }
    fun close() { closed = true; cancel(); tts?.shutdown(); tts = null }
}
