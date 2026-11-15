package app.chatclumer.android.link

import java.net.URI
import java.net.URISyntaxException

data class PairPayload(val baseUrl: String, val token: String)

object TokenPolicy {
    fun accept(token: String): Boolean {
        if (token.length !in 1..512) return false
        return token.none { it.isISOControl() || it.isWhitespace() }
    }
}

/**
 * QR and deep-link payload: `chatclumer://pair?u=<urlencoded base>&t=<token>`.
 * The computer leaves a base64url token unescaped; percent-encoding is also accepted.
 * The first value wins if a key is repeated.
 */
object PairLinks {
    fun parse(raw: String?): PairPayload? {
        val text = raw?.trim().orEmpty()
        if (text.isEmpty() || text.length > 4096) return null
        val uri = try {
            URI(text)
        } catch (_: URISyntaxException) {
            return null
        }
        if (!uri.scheme.equals("chatclumer", ignoreCase = true)) return null
        if (!uri.host.equals("pair", ignoreCase = true)) return null
        val query = uri.rawQuery ?: return null
        val params = parseQuery(query) ?: return null
        val base = params["u"]?.let { UrlPolicy.normalizeBase(it) } ?: return null
        val token = params["t"]?.trim().orEmpty()
        if (!TokenPolicy.accept(token)) return null
        return PairPayload(base, token)
    }

    private fun parseQuery(raw: String): Map<String, String>? {
        val out = linkedMapOf<String, String>()
        for (part in raw.split('&')) {
            if (part.isEmpty()) continue
            val idx = part.indexOf('=')
            val key = UrlPolicy.decodeQueryComponent(if (idx >= 0) part.substring(0, idx) else part) ?: return null
            val value = UrlPolicy.decodeQueryComponent(if (idx >= 0) part.substring(idx + 1) else "") ?: return null
            if (key.isNotEmpty() && key !in out) out[key] = value
        }
        return out
    }
}

fun maskToken(token: String): String {
    if (token.length < 8) return "••••"
    return "••••" + token.takeLast(4)
}

fun displayVersion(raw: String): String =
    raw.filter { it.isLetterOrDigit() || it == '.' || it == '-' || it == '_' }.take(32)
