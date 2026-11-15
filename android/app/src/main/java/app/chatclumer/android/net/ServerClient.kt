package app.chatclumer.android.net

import app.chatclumer.android.link.UrlPolicy
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

sealed class Probe {
    data class Online(val version: String, val auth: Boolean) : Probe()
    data object NotChatClumer : Probe()
    data class RateLimited(val retryAfterSeconds: Long) : Probe()
    data class Failed(val kind: String) : Probe()
}

/**
 * GET /m/ping with no Authorization header. A wrong bearer on ping counts toward the
 * computer's lockout, so this client never sends the token here.
 */
class ServerClient(
    private val open: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
    private val connectTimeoutMs: Int = 8_000,
    private val readTimeoutMs: Int = 8_000,
) {
    fun ping(baseUrl: String): Probe {
        val url = try {
            URL(UrlPolicy.pingUrl(baseUrl))
        } catch (_: Exception) {
            return Probe.Failed("url")
        }
        val conn = try {
            open(url)
        } catch (_: Exception) {
            return Probe.Failed("network")
        }
        return try {
            conn.requestMethod = "GET"
            conn.instanceFollowRedirects = false
            conn.connectTimeout = connectTimeoutMs
            conn.readTimeout = readTimeoutMs
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("User-Agent", "ChatCluster-Android")
            val code = conn.responseCode
            if (code == 429) {
                return Probe.RateLimited(RateLimit.holdSeconds(conn.getHeaderField("Retry-After")))
            }
            if (code != 200) return Probe.Failed("http")
            val body = readLimited(conn.inputStream)
            val info = PingJson.parse(body) ?: return Probe.Failed("parse")
            if (info.app != CHATCLUMER_APP_ID) return Probe.NotChatClumer
            Probe.Online(info.version, info.auth)
        } catch (_: IOException) {
            Probe.Failed("network")
        } catch (_: Exception) {
            Probe.Failed("network")
        } finally {
            conn.disconnect()
        }
    }

    private fun readLimited(stream: java.io.InputStream): String {
        stream.use { input ->
            val buffer = ByteArray(8192)
            val read = input.read(buffer)
            if (read <= 0) return ""
            return String(buffer, 0, read, Charsets.UTF_8)
        }
    }
}
