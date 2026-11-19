// Demo project, no real data.
// Plugins come from Maven Central first and the Gradle plugin portal second: on
// 18 November 2026 the portal once failed to serve the Kotlin plugin's BOM.
pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

rootProject.name = "demo-shop-kotlin"
