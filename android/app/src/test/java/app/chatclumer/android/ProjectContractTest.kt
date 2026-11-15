package app.chatclumer.android

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProjectContractTest {
    @Test
    fun manifestDeclaresDeepLinkAndCleartextConfig() {
        val manifest = read("app/src/main/AndroidManifest.xml")
        assertTrue(manifest.contains("android:scheme=\"chatclumer\""))
        assertTrue(manifest.contains("android:host=\"pair\""))
        assertTrue(manifest.contains("network_security_config"))
        assertTrue(manifest.contains("android.permission.CAMERA"))
        assertTrue(manifest.contains("tools:node=\"remove\""))
        val network = read("app/src/main/res/xml/network_security_config.xml")
        assertTrue(network.contains("cleartextTrafficPermitted=\"true\""))
        assertTrue(network.contains("局域网"))
    }

    @Test
    fun gradlePinsSdkAndDoesNotDependOnPlayServices() {
        val gradle = read("app/build.gradle.kts")
        assertTrue(gradle.contains("minSdk = 24"))
        assertTrue(gradle.contains("targetSdk = 36"))
        assertTrue(gradle.contains("compileSdk = 36"))
        assertFalse(gradle.contains("play-services"))
        assertTrue(gradle.contains("zxing-android-embedded"))
        assertTrue(gradle.contains("security-crypto"))
    }

    @Test
    fun userVisibleStringsAreChinese() {
        val strings = read("app/src/main/res/values/strings.xml")
        assertTrue(strings.contains("暂时不能再试"))
        assertTrue(strings.contains("重新扫描"))
        assertFalse(strings.contains(">Retry<"))
        assertFalse(strings.contains(">Scan<"))
        assertFalse(strings.contains(">Connect<"))
        assertFalse(strings.contains(">Settings<"))
    }

    private fun read(relative: String): String {
        val name = relative.removePrefix("app/")
        val candidates = listOf(File(name), File(relative), File("../$relative"))
        val file = candidates.firstOrNull { it.isFile } ?: error("missing $relative from ${File(".").absolutePath}")
        return file.readText()
    }
}
