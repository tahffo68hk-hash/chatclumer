package app.chatclumer.android.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ComputerStoreTest {
    private var clock = 1_000_000L
    private val bucket = MemoryBucket()
    private val store = ComputerStore(bucket) { clock }

    @Test
    fun roundTripsSecretsAndMasksToString() {
        val token = "tok\"en\\with/中文"
        val saved = store.upsert("http://192.168.1.5:43123", token, "0.6.0", "书房")
        val again = ComputerStore(bucket) { clock }.list().single()
        assertEquals(saved.id, again.id)
        assertEquals("书房", again.name)
        assertEquals(token, again.token)
        assertEquals("0.6.0", again.serverVersion)
        assertFalse(again.toString().contains(token))
        assertTrue(again.toString().contains("••••"))
    }

    @Test
    fun sameAddressUpdatesTokenAndKeepsName() {
        val first = store.upsert("http://192.168.1.5:43123", "old-token-value", "0.5.0", "书房")
        clock += 5_000
        val second = store.upsert("http://192.168.1.5:43123", "new-token-value", "0.6.0")
        assertEquals(first.id, second.id)
        assertEquals("书房", second.name)
        assertEquals("new-token-value", second.token)
        assertEquals("0.6.0", second.serverVersion)
        assertEquals(1, store.list().size)
        assertEquals(second.id, store.list().first().id)
    }

    @Test
    fun renameAndDelete() {
        val saved = store.upsert("http://10.0.0.8:43123", "token-one", "0.6.0")
        assertNull(store.rename(saved.id, "   "))
        assertEquals("书房电脑", store.rename(saved.id, "书房电脑")?.name)
        store.delete(saved.id)
        assertTrue(store.list().isEmpty())
    }

    @Test
    fun corruptPayloadDoesNotThrow() {
        val bucket = MemoryBucket()
        bucket.put("computers", "{not json")
        assertTrue(ComputerStore(bucket).list().isEmpty())
    }

    @Test
    fun rateHoldSurvivesAndDoesNotShrink() {
        val origin = "http://192.168.1.5:43123"
        assertEquals(0L, store.remainingHoldSeconds(origin, clock))
        assertEquals(600L, store.rememberHold(origin, 600, clock))
        assertEquals(600L, store.rememberHold(origin, 30, clock))
        clock += 60_000
        assertEquals(540L, store.remainingHoldSeconds(origin, clock))
        val reloaded = ComputerStore(bucket) { clock }
        assertEquals(540L, reloaded.remainingHoldSeconds(origin, clock))
        clock += 540_000
        assertEquals(0L, reloaded.remainingHoldSeconds(origin, clock))
    }
}
