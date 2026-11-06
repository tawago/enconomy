// JVM-only test bench for ../common (the code the app patch adds to commonMain).
// Run: JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gradlew test
plugins { kotlin("jvm") version "2.2.20" }

kotlin {
    jvmToolchain(21)
    sourceSets["main"].kotlin.srcDir("../common")
}

dependencies {
    implementation("org.kotlincrypto.hash:sha3:0.8.0") // same lib + version the app uses for Keccak256
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    // vectors in, vectors out (for ../noble-check.cjs)
    systemProperty("vectors.dir", file("../vectors").absolutePath)
    testLogging { events("passed", "failed"); showStandardStreams = true; exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL }
    outputs.upToDateWhen { false }
}
