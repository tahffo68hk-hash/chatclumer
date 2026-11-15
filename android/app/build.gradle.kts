import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val keystorePath = System.getenv("CHATCLUMER_KEYSTORE")?.trim().orEmpty()
val keystorePassword = System.getenv("CHATCLUMER_KEYSTORE_PASSWORD")
val keyAliasEnv = System.getenv("CHATCLUMER_KEY_ALIAS")?.trim().orEmpty()
val keyPasswordEnv = System.getenv("CHATCLUMER_KEY_PASSWORD")
val releaseKeystore = File(keystorePath)
val hasReleaseKey = keystorePath.isNotEmpty() &&
    releaseKeystore.isFile &&
    !keystorePassword.isNullOrEmpty() &&
    keyAliasEnv.isNotEmpty()

if (!hasReleaseKey) {
    logger.lifecycle(
        "Release signing: CHATCLUMER_KEYSTORE is absent or incomplete. " +
            "The release APK will be signed with the debug keystore so it can still be installed. " +
            "This is not a store signature. See android/README.md.",
    )
}

android {
    namespace = "app.chatclumer.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.chatclumer.android"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.6.0"
    }

    signingConfigs {
        create("releaseFromEnv") {
            if (hasReleaseKey) {
                storeFile = releaseKeystore
                storePassword = keystorePassword
                keyAlias = keyAliasEnv
                keyPassword = if (keyPasswordEnv.isNullOrEmpty()) keystorePassword else keyPasswordEnv
            }
        }
    }

    buildTypes {
        debug {
            isDebuggable = true
        }
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            isDebuggable = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = if (hasReleaseKey) {
                signingConfigs.getByName("releaseFromEnv")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    testOptions {
        unitTests.isIncludeAndroidResources = false
    }
}

base {
    archivesName.set("chatclumer-android")
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")

    testImplementation("junit:junit:4.13.2")
}
