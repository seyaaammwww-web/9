plugins {
    id("com.android.application")
    id("kotlin-android")
    id("dev.flutter.flutter-gradle-plugin")
    id("com.google.gms.google-services")
}

android {
    namespace = "com.example.school_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        applicationId = "com.example.school_app"
        
        // 👇 التعديل هنا: خليناها 24 بدل 23 عشان تحل مشكلة image_picker
        minSdkVersion(24)
        
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        
        // ده مهم عشان مشكلة الفايربيز
        multiDexEnabled = true
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

dependencies {
    // مكتبة MultiDex
    implementation("androidx.multidex:multidex:2.0.1")
    
    // Firebase BOM لتجنب تعارض الإصدارات
    implementation(platform("com.google.firebase:firebase-bom:33.1.0"))
}