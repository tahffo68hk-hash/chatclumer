package app.chatclumer.android.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlPolicyTest {
    private val base = "http://192.168.1.5:43123"

    @Test
    fun acceptsHttpAndHttpsWithHost() {
        assertEquals(base, UrlPolicy.normalizeBase("http://192.168.1.5:43123/"))
        assertEquals("https://pc.example/room", UrlPolicy.normalizeBase("HTTPS://pc.example:443/room/"))
        assertEquals("http://localhost:43123", UrlPolicy.normalizeBase("http://localhost:43123"))
        assertEquals("http://[::1]:43123", UrlPolicy.normalizeBase("http://[::1]:43123"))
    }

    @Test
    fun userInputDefaultsToHttp() {
        assertEquals(base, UrlPolicy.normalizeUserInput("  192.168.1.5:43123 "))
        assertEquals("http://computer.local", UrlPolicy.normalizeUserInput("computer.local"))
    }

    @Test
    fun rejectsNonHttpAndMissingHost() {
        assertNull(UrlPolicy.normalizeBase("ftp://files.example/x"))
        assertNull(UrlPolicy.normalizeBase("file:///tmp/x"))
        assertNull(UrlPolicy.normalizeBase("javascript:alert(1)"))
        assertNull(UrlPolicy.normalizeBase("data:text/html,hi"))
        assertNull(UrlPolicy.normalizeBase("chatclumer://pair"))
        assertNull(UrlPolicy.normalizeBase("http://"))
        assertNull(UrlPolicy.normalizeBase("http:///no-host"))
        assertNull(UrlPolicy.normalizeBase(""))
        assertNull(UrlPolicy.normalizeBase("   "))
        assertNull(UrlPolicy.normalizeBase("http://user:secret@192.168.1.5:43123"))
        assertNull(UrlPolicy.normalizeUserInput("ftp://x"))
    }

    @Test
    fun originIgnoresPathAndTreatsDefaultPortsAsEqual() {
        assertEquals(UrlPolicy.origin(base), UrlPolicy.origin("$base/backend/api/sessions/1/events"))
        assertEquals(UrlPolicy.origin("http://example.com/a"), UrlPolicy.origin("http://example.com:80/b"))
        assertEquals(UrlPolicy.origin("https://example.com"), UrlPolicy.origin("https://example.com:443/x"))
        assertFalse(UrlPolicy.origin(base) == UrlPolicy.origin("http://192.168.1.5:43124/"))
        assertFalse(UrlPolicy.origin(base) == UrlPolicy.origin("https://192.168.1.5:43123/"))
        assertFalse(UrlPolicy.origin(base) == UrlPolicy.origin("http://192.168.1.5.evil.com:43123/"))
        assertFalse(UrlPolicy.origin(base) == UrlPolicy.origin("http://evil.com/"))
    }

    @Test
    fun navigationStaysOnOrigin() {
        assertEquals(UrlPolicy.Decision.ALLOW, UrlPolicy.decide(base, "$base/backend/api/events", false))
        assertEquals(UrlPolicy.Decision.ALLOW, UrlPolicy.decide(base, "/m/pair", false))
        assertEquals(UrlPolicy.Decision.ALLOW, UrlPolicy.decide(base, "about:blank", false))
        assertEquals(UrlPolicy.Decision.EXTERNAL, UrlPolicy.decide(base, "https://example.com/help", true))
        assertEquals(UrlPolicy.Decision.BLOCK, UrlPolicy.decide(base, "https://example.com/help", false))
        assertEquals(UrlPolicy.Decision.BLOCK, UrlPolicy.decide(base, "javascript:alert(1)", true))
        assertEquals(UrlPolicy.Decision.BLOCK, UrlPolicy.decide(base, "intent://scan/#Intent;end", true))
        assertEquals(UrlPolicy.Decision.BLOCK, UrlPolicy.decide(base, "http://evil.example/?token=secret", true))
        assertEquals(UrlPolicy.Decision.EXTERNAL, UrlPolicy.decide(base, "//evil.example/x", true))
        assertEquals(UrlPolicy.Decision.BLOCK, UrlPolicy.decide(base, "//evil.example/x", false))
    }

    @Test
    fun credentialQueryDetection() {
        assertTrue(UrlPolicy.containsCredentialQuery("$base/m/pair?token=abc"))
        assertTrue(UrlPolicy.containsCredentialQuery("chatclumer://pair?u=http%3A%2F%2Fh&t=abc"))
        assertFalse(UrlPolicy.containsCredentialQuery("$base/"))
        assertFalse(UrlPolicy.containsCredentialQuery("$base/backend/api/sessions"))
    }

    @Test
    fun pairUrlEncodesToken() {
        val url = UrlPolicy.pairUrl(base, "a/b+c")
        assertEquals("$base/m/pair?token=a%2Fb%2Bc", url)
        assertFalse(url.contains("a/b+c"))
    }
}
