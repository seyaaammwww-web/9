buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        // 👇 هذا هو السطر الناقص الذي يسبب المشكلة
        // تأكد أن إصدار Android Gradle Plugin متوافق مع مشروعك (عادة موجود، لكن جوجل سيرفس هو المهم هنا)
        classpath("com.android.tools.build:gradle:8.1.0") // تأكد من الإصدار المناسب لك
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:1.8.22") // تأكد من الإصدار المناسب لك
        
        // 👇👇👇 هذا السطر هو حل مشكلة الفايربيز
        classpath("com.google.gms:google-services:4.4.2")
    }
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory = rootProject.layout.buildDirectory.dir("../../build").get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}