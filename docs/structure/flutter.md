# Flutter 目录规范

示例以业务优先组织 Dart 文件。模块内区分界面与数据访问，领域用例按需放入 `domain/`。各端宿主工程放在项目根目录的对应平台目录，Dart 代码集中在 `lib/`。[Flutter 架构建议](https://docs.flutter.dev/app-architecture/recommendations) · [Dart 命名规范](https://dart.dev/effective-dart/style)

```text
flutter_app/
├── pubspec.yaml
├── lib/
│   ├── main.dart
│   └── src/
│       ├── app.dart
│       ├── routing/app_router.dart
│       ├── features/checkout/
│       │   ├── presentation/
│       │   │   ├── checkout_screen.dart
│       │   │   └── checkout_view_model.dart
│       │   └── data/
│       │       ├── checkout_repository.dart
│       │       └── checkout_api_service.dart
│       └── shared/
│           ├── networking/
│           └── ui/
├── assets/
├── test/features/checkout/
├── integration_test/
├── android/
└── ios/
```
