package app.chatclumer.android.net

import java.io.Closeable
import java.net.ServerSocket
import java.net.Socket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PingJsonTest {
    @Test
    fun parsesContractBody() {
        val info = PingJson.parse("""{"app":"chatclumer","version":"0.6.0","auth":false}""")
        assertEquals(CHATCLUMER_APP_ID, info?.app)
        assertEquals("0.6.0", info?.version)
        assertEquals(false, info?.auth)
    }

    @Test
    fun acceptsExtraFieldsAndWhitespace() {
        val info = PingJson.parse("{\n  \"version\": \"0.6.0\", \"auth\": true, \"app\": \"chatclumer\", \"extra\": 1\n}")
        assertEquals(true, info?.auth)
        assertEquals("0.6.0", info?.version)
    }

    @Test
    fun rejectsWrongShape() {
        assertNull(PingJson.parse(""))
        assertNull(PingJson.parse("<html>401</html>"))
        assertNull(PingJson.parse("""{"app":"other","version":"0.6.0","auth":false}""").let {
            if (it?.app == CHATCLUMER_APP_ID) it else if (it == null) null else it
        }?.takeIf { it.app == CHATCLUMER_APP_ID })
        assertEquals("other", PingJson.parse("""{"app":"other","version":"1","auth":false}""")?.app)
        assertNull(PingJson.parse("""{"app":"chatclumer","auth":false}"""))
        assertNull(PingJson.parse("""{"app":"chatclumer","version":"0.6.0","auth":"false"}"""))
    }
}

class RateLimitTest {
    @Test
    fun parsesRetryAfterSeconds() {
        assertEquals(600L, RateLimit.holdSeconds("600"))
        assertEquals(120L, RateLimit.holdSeconds(" 120 "))
        assertEquals(1L, RateLimit.holdSeconds("0"))
        assertEquals(RateLimit.DEFAULT_SECONDS, RateLimit.holdSeconds(null))
        assertEquals(RateLimit.DEFAULT_SECONDS, RateLimit.holdSeconds("soon"))
        assertEquals(RateLimit.MAX_SECONDS, RateLimit.holdSeconds("99999999"))
    }

    @Test
    fun readsHeaderIgnoringCase() {
        assertEquals("90", RateLimit.headerValue(mapOf("Retry-After" to "90")))
        assertEquals("90", RateLimit.headerValue(mapOf("retry-after" to "90")))
        assertNull(RateLimit.headerValue(emptyMap()))
    }

    @Test
    fun formatsChineseWait() {
        assertEquals("45 秒", RateLimit.formatWait(45))
        assertEquals("1 分钟", RateLimit.formatWait(60))
        assertEquals("1 分 30 秒", RateLimit.formatWait(90))
        assertEquals("10 分钟", RateLimit.formatWait(600))
        assertEquals("10 分 1 秒", RateLimit.formatWait(601))
    }

    @Test
    fun holdBlocksFurtherAttemptsUntilDeadline() {
        val gate = RateLimitGate()
        val origin = "http://192.168.1.5:43123"
        val now = 1_000_000L
        assertEquals(0L, gate.remainingSeconds(origin, now))
        assertEquals(600L, gate.hold(origin, 600, now))
        assertEquals(590L, gate.remainingSeconds(origin, now + 10_000))
        assertEquals(600L, gate.hold(origin, 30, now))
        assertTrue(gate.remainingSeconds(origin, now + 599_000) > 0L)
        assertEquals(0L, gate.remainingSeconds(origin, now + 600_000))
        assertEquals(0L, gate.remainingSeconds("http://other:43123", now))
    }
}

class WebErrorsTest {
    @Test
    fun classifiesStatuses() {
        assertEquals(PageProblem.UNAUTHORIZED, WebErrors.fromHttpStatus(401))
        assertEquals(PageProblem.RATE_LIMITED, WebErrors.fromHttpStatus(429))
        assertEquals(PageProblem.UNAVAILABLE, WebErrors.fromHttpStatus(500))
        assertEquals(PageProblem.UNAVAILABLE, WebErrors.fromHttpStatus(404))
        assertNull(WebErrors.fromHttpStatus(200))
        assertNull(WebErrors.fromHttpStatus(302))
    }
}

class ServerClientTest {
    @Test
    fun pingReadsContractWithoutSendingCredentials() {
        var authorization: String? = "unset"
        var hits = 0
        val body = """{"app":"chatclumer","version":"0.6.0","auth":false}""".toByteArray()
        LoopbackHttp { request ->
            hits++
            authorization = request.headers.entries.firstOrNull { it.key.equals("Authorization", true) }?.value
            if (request.path == "/m/ping") {
                LoopbackHttp.Response(
                    200,
                    mapOf(
                        "Access-Control-Allow-Origin" to "*",
                        "Content-Type" to "application/json; charset=utf-8",
                    ),
                    body,
                )
            } else {
                hits += 100
                LoopbackHttp.Response(500)
            }
        }.use { server ->
            val probe = ServerClient().ping("http://127.0.0.1:${server.port}")
            assertTrue(probe is Probe.Online)
            probe as Probe.Online
            assertEquals("0.6.0", probe.version)
            assertEquals(false, probe.auth)
            assertNull(authorization)
            assertEquals(1, hits)
        }
    }

    @Test
    fun pingDoesNotFollowRedirects() {
        var stolen = 0
        LoopbackHttp { request ->
            if (request.path == "/stolen") stolen++
            LoopbackHttp.Response(302, mapOf("Location" to "/stolen"))
        }.use { server ->
            val probe = ServerClient().ping("http://127.0.0.1:${server.port}")
            assertEquals(Probe.Failed("http"), probe)
            assertEquals(0, stolen)
        }
    }

    @Test
    fun pingReportsRateLimitAndWrongApp() {
        val other = """{"app":"not-chat","version":"0.6.0","auth":false}""".toByteArray()
        LoopbackHttp { request ->
            when (request.path) {
                "/limited/m/ping" -> LoopbackHttp.Response(429, mapOf("Retry-After" to "600"))
                "/other/m/ping" -> LoopbackHttp.Response(200, body = other)
                else -> LoopbackHttp.Response(404)
            }
        }.use { server ->
            val limited = ServerClient().ping("http://127.0.0.1:${server.port}/limited")
            assertEquals(Probe.RateLimited(600), limited)
            val foreign = ServerClient().ping("http://127.0.0.1:${server.port}/other")
            assertEquals(Probe.NotChatClumer, foreign)
        }
    }

    @Test
    fun pingNetworkFailureHasNoDetail() {
        val port = ServerSocket(0).use { it.localPort }
        val probe = ServerClient().ping("http://127.0.0.1:$port")
        assertEquals(Probe.Failed("network"), probe)
        assertTrue(probe.toString().length < 80)
    }
}

private class LoopbackHttp(
    private val handle: (Request) -> Response,
) : Closeable {
    data class Request(val path: String, val headers: Map<String, String>)
    data class Response(
        val status: Int,
        val headers: Map<String, String> = emptyMap(),
        val body: ByteArray = ByteArray(0),
    )

    private val socket = ServerSocket(0)
    val port: Int = socket.localPort
    private val thread = Thread {
        while (!socket.isClosed) {
            val client = try {
                socket.accept()
            } catch (_: Exception) {
                break
            }
            Thread { serve(client) }.apply { isDaemon = true }.start()
        }
    }.apply {
        isDaemon = true
        start()
    }

    private fun serve(client: Socket) {
        client.use { sock ->
            sock.soTimeout = 3_000
            val input = sock.getInputStream().bufferedReader(Charsets.ISO_8859_1)
            val requestLine = input.readLine() ?: return
            val path = requestLine.split(" ").getOrElse(1) { "/" }.substringBefore("?")
            val headers = linkedMapOf<String, String>()
            while (true) {
                val line = input.readLine() ?: break
                if (line.isEmpty()) break
                val idx = line.indexOf(':')
                if (idx > 0) headers[line.substring(0, idx).trim()] = line.substring(idx + 1).trim()
            }
            val response = handle(Request(path, headers))
            val reason = when (response.status) {
                200 -> "OK"
                302 -> "Found"
                429 -> "Too Many Requests"
                else -> "Error"
            }
            val head = buildString {
                append("HTTP/1.1 ${response.status} $reason\r\n")
                append("Content-Length: ${response.body.size}\r\n")
                append("Connection: close\r\n")
                response.headers.forEach { (key, value) -> append("$key: $value\r\n") }
                append("\r\n")
            }
            val out = sock.getOutputStream()
            out.write(head.toByteArray(Charsets.ISO_8859_1))
            out.write(response.body)
            out.flush()
        }
    }

    override fun close() {
        socket.close()
        thread.join(1000)
    }
}
