package app.chatclumer.android.link

import java.net.URI
import java.net.URISyntaxException
import java.net.URLEncoder

/**
 * Rules for the computer address and for which navigations may stay inside the WebView.
 * The configured origin is scheme + host + port. Paths on that origin are the app itself.
 */
object UrlPolicy {
    private val credentialKeys = setOf("token", "t", "access_token", "password", "code")

    fun normalizeUserInput(raw: String): String? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null
        val withScheme = if ("://" in trimmed) trimmed else "http://$trimmed"
        return normalizeBase(withScheme)
    }

    fun normalizeBase(raw: String): String? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty() || trimmed.length > 2048) return null
        if (trimmed.any { it.isISOControl() || it.isWhitespace() }) return null
        val uri = try {
            URI(trimmed)
        } catch (_: URISyntaxException) {
            return null
        }
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null
        if (!uri.rawUserInfo.isNullOrEmpty()) return null
        val host = bareHost(uri) ?: return null
        if (host.contains('\\')) return null
        val explicit = uri.port
        if (explicit == 0 || explicit > 65535) return null
        val defaultPort = if (scheme == "https") 443 else 80
        val portPart = if (explicit == -1 || explicit == defaultPort) -1 else explicit
        val rawPath = uri.rawPath ?: ""
        if (rawPath.contains("..")) return null
        var path = if (rawPath == "/") "" else rawPath.trimEnd('/')
        if (path.isNotEmpty() && !path.startsWith("/")) return null
        val built = try {
            URI(scheme, null, host, portPart, path, null, null).normalize()
        } catch (_: URISyntaxException) {
            return null
        }
        val builtPath = built.path ?: ""
        if (builtPath.contains("..")) return null
        return built.toASCIIString().trimEnd('/')
    }

    fun origin(url: String): String? {
        val uri = try {
            URI(url.trim())
        } catch (_: URISyntaxException) {
            return null
        }
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null
        if (!uri.rawUserInfo.isNullOrEmpty()) return null
        val host = bareHost(uri) ?: return null
        val port = when {
            uri.port != -1 -> uri.port
            scheme == "https" -> 443
            else -> 80
        }
        if (port !in 1..65535) return null
        return "$scheme://${displayHost(host)}:$port"
    }

    fun hostLabel(baseUrl: String): String {
        val uri = try {
            URI(baseUrl)
        } catch (_: URISyntaxException) {
            return baseUrl
        }
        val host = bareHost(uri) ?: return baseUrl
        val shown = displayHost(host)
        return if (uri.port == -1) shown else "$shown:${uri.port}"
    }

    fun containsCredentialQuery(url: String): Boolean {
        val raw = try {
            URI(url.trim()).rawQuery
        } catch (_: URISyntaxException) {
            null
        } ?: return false
        return raw.split('&').any { part ->
            val key = decodeQueryComponent(part.substringBefore('='))?.lowercase()
            key in credentialKeys
        }
    }

    enum class Decision { ALLOW, EXTERNAL, BLOCK }

    fun decide(baseUrl: String, target: String, userGesture: Boolean): Decision {
        val trimmed = target.trim()
        if (trimmed.isEmpty()) return Decision.BLOCK
        if (trimmed == "about:blank" || trimmed.startsWith("about:blank#") || trimmed.startsWith("about:blank?")) {
            return Decision.ALLOW
        }
        val resolved = resolve(baseUrl, trimmed)
        val baseOrigin = origin(baseUrl) ?: return Decision.BLOCK
        val targetOrigin = origin(resolved)
        if (targetOrigin != null && targetOrigin == baseOrigin) {
            return Decision.ALLOW
        }
        if (containsCredentialQuery(resolved)) return Decision.BLOCK
        val scheme = try {
            URI(resolved).scheme?.lowercase()
        } catch (_: URISyntaxException) {
            null
        }
        if ((scheme == "http" || scheme == "https") && userGesture) return Decision.EXTERNAL
        return Decision.BLOCK
    }

    fun resolve(baseUrl: String, target: String): String {
        return try {
            URI(baseUrl).resolve(target).toASCIIString()
        } catch (_: Exception) {
            target
        }
    }

    fun pairUrl(baseUrl: String, token: String): String {
        val encoded = URLEncoder.encode(token, "UTF-8")
        return baseUrl.trimEnd('/') + "/m/pair?token=" + encoded
    }

    fun pingUrl(baseUrl: String): String = baseUrl.trimEnd('/') + "/m/ping"

    fun rootUrl(baseUrl: String): String = baseUrl.trimEnd('/') + "/"

    private fun bareHost(uri: URI): String? {
        val raw = uri.host ?: return null
        val stripped = if (raw.startsWith("[") && raw.endsWith("]") && raw.length > 2) {
            raw.substring(1, raw.length - 1)
        } else {
            raw
        }
        return stripped.lowercase().takeIf { it.isNotEmpty() }
    }

    private fun displayHost(host: String): String = if (':' in host) "[$host]" else host

    internal fun decodeQueryComponent(raw: String): String? {
        return try {
            java.net.URLDecoder.decode(raw, "UTF-8")
        } catch (_: IllegalArgumentException) {
            null
        }
    }
}
