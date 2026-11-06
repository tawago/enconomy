// Type-check only: compiles ../../android/AndroidFrameKeystore.kt + ../../common against the SDK's android.jar.
// Nothing here runs (android.jar is stubs). Run: ./gradlew :android-compile:compileKotlin
plugins { kotlin("jvm") }

val sdk = file((System.getenv("ANDROID_HOME") ?: "${System.getProperty("user.home")}/Library/Android/sdk") + "/platforms/android-35/android.jar")

kotlin {
    jvmToolchain(21)
    sourceSets["main"].kotlin.srcDir("../../android")
    sourceSets["main"].kotlin.srcDir("../../common")
}

dependencies {
    compileOnly(files(sdk))
    implementation("org.kotlincrypto.hash:sha3:0.8.0")
}
