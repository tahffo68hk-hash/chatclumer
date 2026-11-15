package app.chatclumer.android.data

import app.chatclumer.android.link.TokenPolicy
import app.chatclumer.android.link.UrlPolicy
import app.chatclumer.android.link.maskToken
import java.util.UUID

data class SavedComputer(
    val id: String,
    val name: String,
    val baseUrl: String,
    val token: String,
    val serverVersion: String,
    val lastConnectedAt: Long,
) {
    override fun toString(): String =
        "SavedComputer(id=$id, name=$name, baseUrl=$baseUrl, token=${maskToken(token)}, serverVersion=$serverVersion)"
}

interface StringBucket {
    fun get(key: String): String?
    fun put(key: String, value: String)
}

class MemoryBucket : StringBucket {
    private val map = linkedMapOf<String, String>()
    override fun get(key: String): String? = map[key]
    override fun put(key: String, value: String) {
        map[key] = value
    }
}

class ComputerStore(
    private val bucket: StringBucket,
    private val now: () -> Long = System::currentTimeMillis,
) {
    fun list(): List<SavedComputer> =
        ComputerCodec.decode(bucket.get(COMPUTERS).orEmpty())
            .sortedByDescending { it.lastConnectedAt }

    fun findById(id: String): SavedComputer? = list().firstOrNull { it.id == id }

    fun upsert(baseUrl: String, token: String, serverVersion: String, name: String? = null): SavedComputer {
        val all = list().toMutableList()
        val existing = all.firstOrNull { it.baseUrl == baseUrl }
        val saved = if (existing == null) {
            SavedComputer(
                id = UUID.randomUUID().toString(),
                name = cleanName(name, baseUrl),
                baseUrl = baseUrl,
                token = token,
                serverVersion = serverVersion,
                lastConnectedAt = now(),
            )
        } else {
            existing.copy(
                token = token,
                serverVersion = serverVersion.ifBlank { existing.serverVersion },
                lastConnectedAt = now(),
                name = if (name.isNullOrBlank()) existing.name else cleanName(name, baseUrl),
            )
        }
        all.removeAll { it.baseUrl == baseUrl }
        all.add(saved)
        bucket.put(COMPUTERS, ComputerCodec.encode(all))
        return saved
    }

    fun rename(id: String, name: String): SavedComputer? {
        val cleaned = name.filter { !it.isISOControl() }.trim().take(40)
        if (cleaned.isEmpty()) return null
        val all = list().map { if (it.id == id) it.copy(name = cleaned) else it }
        if (all.none { it.id == id }) return null
        bucket.put(COMPUTERS, ComputerCodec.encode(all))
        return all.first { it.id == id }
    }

    fun delete(id: String) {
        val all = list().filterNot { it.id == id }
        bucket.put(COMPUTERS, ComputerCodec.encode(all))
    }

    fun remainingHoldSeconds(origin: String, nowMs: Long): Long {
        val until = holds()[origin] ?: return 0
        if (until <= nowMs) return 0
        return ((until - nowMs) + 999) / 1000
    }

    fun rememberHold(origin: String, seconds: Long, nowMs: Long): Long {
        val map = holds().toMutableMap()
        val until = nowMs + seconds.coerceAtLeast(1) * 1000
        map[origin] = maxOf(map[origin] ?: 0L, until)
        map.entries.removeAll { it.value <= nowMs }
        bucket.put(HOLDS, ComputerCodec.encodeHolds(map))
        return remainingHoldSeconds(origin, nowMs)
    }

    private fun holds(): Map<String, Long> {
        val current = now()
        return ComputerCodec.decodeHolds(bucket.get(HOLDS).orEmpty()).filterValues { it > current }
    }

    private fun cleanName(raw: String?, baseUrl: String): String {
        val cleaned = raw?.filter { !it.isISOControl() }?.trim()?.take(40).orEmpty()
        return cleaned.ifEmpty { UrlPolicy.hostLabel(baseUrl) }
    }

    companion object {
        private const val COMPUTERS = "computers"
        private const val HOLDS = "rate_holds"
    }
}

internal object ComputerCodec {
    fun encode(items: List<SavedComputer>): String = buildString {
        append('[')
        items.forEachIndexed { index, item ->
            if (index > 0) append(',')
            append('{')
            field("id", item.id)
            append(',')
            field("name", item.name)
            append(',')
            field("baseUrl", item.baseUrl)
            append(',')
            field("token", item.token)
            append(',')
            field("serverVersion", item.serverVersion)
            append(',')
            append("\"lastConnectedAt\":").append(item.lastConnectedAt)
            append('}')
        }
        append(']')
    }

    fun decode(raw: String): List<SavedComputer> {
        if (raw.isBlank()) return emptyList()
        val value = try {
            JsonReader(raw).parseValue()
        } catch (_: Exception) {
            return emptyList()
        }
        val list = value as? List<*> ?: return emptyList()
        return list.mapNotNull { item ->
            val obj = item as? Map<*, *> ?: return@mapNotNull null
            val id = obj["id"] as? String ?: return@mapNotNull null
            val name = obj["name"] as? String ?: return@mapNotNull null
            val baseUrl = obj["baseUrl"] as? String ?: return@mapNotNull null
            val token = obj["token"] as? String ?: return@mapNotNull null
            val version = obj["serverVersion"] as? String ?: ""
            val at = obj["lastConnectedAt"] as? Long ?: return@mapNotNull null
            if (id.isBlank() || name.isBlank()) return@mapNotNull null
            if (UrlPolicy.normalizeBase(baseUrl) != baseUrl) return@mapNotNull null
            if (!TokenPolicy.accept(token)) return@mapNotNull null
            SavedComputer(id, name, baseUrl, token, version, at)
        }
    }

    fun encodeHolds(holds: Map<String, Long>): String = buildString {
        append('{')
        holds.entries.forEachIndexed { index, (origin, until) ->
            if (index > 0) append(',')
            append(JsonReader.quote(origin)).append(':').append(until)
        }
        append('}')
    }

    fun decodeHolds(raw: String): Map<String, Long> {
        if (raw.isBlank()) return emptyMap()
        val value = try {
            JsonReader(raw).parseValue()
        } catch (_: Exception) {
            return emptyMap()
        }
        val obj = value as? Map<*, *> ?: return emptyMap()
        val out = linkedMapOf<String, Long>()
        for ((key, item) in obj) {
            val origin = key as? String ?: continue
            val until = item as? Long ?: continue
            out[origin] = until
        }
        return out
    }

    private fun StringBuilder.field(name: String, value: String) {
        append(JsonReader.quote(name)).append(':').append(JsonReader.quote(value))
    }
}

internal class JsonReader(private val text: String) {
    private var i = 0

    fun parseValue(): Any? {
        skip()
        if (i >= text.length) throw IllegalArgumentException("empty")
        return when (text[i]) {
            '{' -> parseObject()
            '[' -> parseArray()
            '"' -> parseString()
            '-', in '0'..'9' -> parseNumber()
            else -> throw IllegalArgumentException("value")
        }
    }

    private fun parseObject(): Map<String, Any?> {
        expect('{')
        val out = linkedMapOf<String, Any?>()
        skip()
        if (peek('}')) {
            i++
            return out
        }
        while (true) {
            skip()
            val key = parseString()
            skip()
            expect(':')
            val value = parseValue()
            out[key] = value
            skip()
            when {
                peek(',') -> i++
                peek('}') -> {
                    i++
                    return out
                }
                else -> throw IllegalArgumentException("object")
            }
        }
    }

    private fun parseArray(): List<Any?> {
        expect('[')
        val out = mutableListOf<Any?>()
        skip()
        if (peek(']')) {
            i++
            return out
        }
        while (true) {
            out.add(parseValue())
            skip()
            when {
                peek(',') -> i++
                peek(']') -> {
                    i++
                    return out
                }
                else -> throw IllegalArgumentException("array")
            }
        }
    }

    private fun parseString(): String {
        expect('"')
        val out = StringBuilder()
        while (i < text.length) {
            val c = text[i++]
            when (c) {
                '"' -> return out.toString()
                '\\' -> {
                    if (i >= text.length) throw IllegalArgumentException("escape")
                    when (val n = text[i++]) {
                        '"', '\\', '/' -> out.append(n)
                        'n' -> out.append('\n')
                        'r' -> out.append('\r')
                        't' -> out.append('\t')
                        'u' -> {
                            if (i + 4 > text.length) throw IllegalArgumentException("unicode")
                            val code = text.substring(i, i + 4).toInt(16)
                            out.append(code.toChar())
                            i += 4
                        }
                        else -> throw IllegalArgumentException("escape")
                    }
                }
                else -> {
                    if (c < ' ') throw IllegalArgumentException("control")
                    out.append(c)
                }
            }
        }
        throw IllegalArgumentException("string")
    }

    private fun parseNumber(): Long {
        val start = i
        if (peek('-')) i++
        if (i >= text.length || !text[i].isDigit()) throw IllegalArgumentException("number")
        while (i < text.length && text[i].isDigit()) i++
        if (i < text.length && (text[i] == '.' || text[i] == 'e' || text[i] == 'E')) {
            throw IllegalArgumentException("fraction")
        }
        return text.substring(start, i).toLong()
    }

    private fun skip() {
        while (i < text.length && text[i].isWhitespace()) i++
    }

    private fun expect(c: Char) {
        skip()
        if (i >= text.length || text[i] != c) throw IllegalArgumentException("expected $c")
        i++
    }

    private fun peek(c: Char): Boolean = i < text.length && text[i] == c

    companion object {
        fun quote(value: String): String = buildString {
            append('"')
            for (c in value) {
                when (c) {
                    '"' -> append("\\\"")
                    '\\' -> append("\\\\")
                    '\n' -> append("\\n")
                    '\r' -> append("\\r")
                    '\t' -> append("\\t")
                    else -> if (c < ' ') append("\\u%04x".format(c.code)) else append(c)
                }
            }
            append('"')
        }
    }
}
