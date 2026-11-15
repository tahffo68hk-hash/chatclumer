package app.chatclumer.android.net

/**
 * The computer locks an IP after 10 distinct bad credentials in 10 minutes and answers
 * 429 with Retry-After (seconds). The phone must show that wait and must not keep calling.
 */
object RateLimit {
    const val DEFAULT_SECONDS = 60L
    const val MAX_SECONDS = 24L * 60L * 60L

    fun holdSeconds(retryAfterHeader: String?): Long {
        val parsed = retryAfterHeader?.trim()?.toLongOrNull()
        val seconds = when {
            parsed == null -> DEFAULT_SECONDS
            parsed < 1L -> 1L
            else -> parsed
        }
        return seconds.coerceAtMost(MAX_SECONDS)
    }

    fun headerValue(headers: Map<String, String>?): String? {
        if (headers == null) return null
        for ((key, value) in headers) {
            if (key.equals("retry-after", ignoreCase = true)) return value
        }
        return null
    }

    /** Phrase placed into a Chinese sentence, for example "10 分钟" or "1 分 30 秒". */
    fun formatWait(totalSeconds: Long): String {
        val seconds = totalSeconds.coerceAtLeast(0)
        val minutes = seconds / 60
        val rest = seconds % 60
        return when {
            minutes > 0 && rest > 0 -> "$minutes 分 $rest 秒"
            minutes > 0 -> "$minutes 分钟"
            else -> "$rest 秒"
        }
    }
}

/**
 * Per-origin deadline. A new 429 extends the hold; it never shortens it.
 * Remaining time is checked before any ping or pair, so a locked computer is not called again.
 */
class RateLimitGate {
    private val untilEpochMs = linkedMapOf<String, Long>()

    fun remainingSeconds(origin: String, nowMs: Long): Long {
        val until = untilEpochMs[origin] ?: return 0
        if (until <= nowMs) {
            untilEpochMs.remove(origin)
            return 0
        }
        return ((until - nowMs) + 999) / 1000
    }

    fun hold(origin: String, seconds: Long, nowMs: Long): Long {
        val until = nowMs + seconds.coerceAtLeast(1) * 1000
        val next = maxOf(untilEpochMs[origin] ?: 0L, until)
        untilEpochMs[origin] = next
        return remainingSeconds(origin, nowMs)
    }

    fun restore(origin: String, untilMs: Long, nowMs: Long) {
        if (untilMs > nowMs) untilEpochMs[origin] = untilMs
    }

    fun until(origin: String): Long = untilEpochMs[origin] ?: 0L
}
