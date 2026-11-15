package app.chatclumer.android.link

import java.net.URLEncoder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairLinksTest {
    private val base = "http://192.168.1.5:43123"
    private val token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"

    @Test
    fun parsesServerPayloadWithRawBase64UrlToken() {
        val payload = "chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}&t=$token"
        val parsed = PairLinks.parse(payload)
        assertEquals(base, parsed?.baseUrl)
        assertEquals(token, parsed?.token)
    }

    @Test
    fun decodesPercentEncodedToken() {
        val parsed = PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}&t=a%2Fb%2Bc")
        assertEquals("a/b+c", parsed?.token)
        assertEquals(base, parsed?.baseUrl)
    }

    @Test
    fun trimsWhitespaceAndIgnoresExtraParams() {
        val parsed = PairLinks.parse("  chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}&from=qr&t=$token  ")
        assertEquals(token, parsed?.token)
    }

    @Test
    fun firstRepeatedKeyWins() {
        val parsed = PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}&t=first-token&t=second-token")
        assertEquals("first-token", parsed?.token)
    }

    @Test
    fun acceptsHostAndSchemeCase() {
        val parsed = PairLinks.parse("CHATCLUMER://PAIR/?u=${URLEncoder.encode("https://pc.tailnet.ts.net", "UTF-8")}&t=$token")
        assertEquals("https://pc.tailnet.ts.net", parsed?.baseUrl)
    }

    @Test
    fun rejectsWrongShape() {
        assertNull(PairLinks.parse(null))
        assertNull(PairLinks.parse(""))
        assertNull(PairLinks.parse(base))
        assertNull(PairLinks.parse("chatclumer://other?u=$base&t=$token"))
        assertNull(PairLinks.parse("https://pair?u=$base&t=$token"))
        assertNull(PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}"))
        assertNull(PairLinks.parse("chatclumer://pair?t=$token"))
        assertNull(PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}&t="))
        assertNull(PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode(base, "UTF-8")}&t=has%20space"))
        assertNull(PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode("javascript:alert(1)", "UTF-8")}&t=$token"))
        assertNull(PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode("http://user:pw@host", "UTF-8")}&t=$token"))
        assertNull(PairLinks.parse("chatclumer://pair?u=${URLEncoder.encode("http:///no-host", "UTF-8")}&t=$token"))
    }

    @Test
    fun maskHidesShortAndLongTokens() {
        assertEquals("••••", maskToken("short"))
        assertTrue(maskToken(token).startsWith("••••"))
        assertTrue(maskToken(token).endsWith(token.takeLast(4)))
        assertTrue(!maskToken(token).contains(token.dropLast(4)))
    }
}
