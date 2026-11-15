package app.chatclumer.android.net

const val CHATCLUMER_APP_ID = "chatclumer"

data class PingInfo(val app: String, val version: String, val auth: Boolean)

/**
 * Parses `{"app":"chatclumer","version":"x.y.z","auth":true|false}`.
 * Extra fields (and the CORS header on the response) are ignored.
 * Ping is called without credentials: a phone normally sees auth=false until it pairs.
 */
object PingJson {
    private val appField = Regex("\"app\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"")
    private val versionField = Regex("\"version\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"")
    private val authField = Regex("\"auth\"\\s*:\\s*(true|false)")

    fun parse(body: String): PingInfo? {
        val text = body.trim()
        if (text.length > 8192 || !text.startsWith("{") || !text.endsWith("}")) return null
        val app = unescape(appField.find(text)?.groupValues?.get(1) ?: return null) ?: return null
        val version = unescape(versionField.find(text)?.groupValues?.get(1) ?: return null) ?: return null
        val auth = authField.find(text)?.groupValues?.get(1)?.toBooleanStrictOrNull() ?: return null
        if (app.isEmpty() || version.isEmpty()) return null
        return PingInfo(app, version, auth)
    }

    private fun unescape(raw: String): String? {
        val out = StringBuilder()
        var i = 0
        while (i < raw.length) {
            val c = raw[i]
            if (c != '\\') {
                out.append(c)
                i++
                continue
            }
            if (i + 1 >= raw.length) return null
            when (val n = raw[i + 1]) {
                '"', '\\', '/' -> out.append(n)
                'n' -> out.append('\n')
                'r' -> out.append('\r')
                't' -> out.append('\t')
                'u' -> {
                    if (i + 6 > raw.length) return null
                    val code = raw.substring(i + 2, i + 6).toIntOrNull(16) ?: return null
                    out.append(code.toChar())
                    i += 6
                    continue
                }
                else -> return null
            }
            i += 2
        }
        return out.toString()
    }
}
