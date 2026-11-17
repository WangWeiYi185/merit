# Android · Kotlin / Compose 目录规范

示例在单个 Gradle 模块内按业务分包。UI 和数据层各有职责，复杂或复用的用例可以单设 `domain/`。[Android 应用架构指南](https://developer.android.com/topic/architecture)

```text
android/app/src/
├── main/
│   ├── AndroidManifest.xml
│   ├── kotlin/com/example/shop/
│   │   ├── MainActivity.kt
│   │   ├── navigation/
│   │   ├── di/
│   │   └── features/checkout/
│   │       ├── ui/
│   │       │   ├── CheckoutScreen.kt
│   │       │   └── CheckoutViewModel.kt
│   │       └── data/
│   │           ├── CheckoutRepository.kt
│   │           ├── local/
│   │           └── remote/
│   └── res/
├── test/
└── androidTest/
```
