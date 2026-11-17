# iOS · Swift / SwiftUI / UIKit 目录规范

示例采用按业务组织的 MVVM。模块的 API、数据映射和 Repository 留在模块的 `Data/`。通用网络和持久化放在 `Services/`。Xcode 工程应按实际配置将源码和资源归入相应 target。[Xcode 文件与目录管理](https://developer.apple.com/documentation/xcode/managing-files-and-folders-in-your-xcode-project)

```text
Shop/
├── Shop.xcodeproj/
├── Shop/
│   ├── App/
│   │   ├── ShopApp.swift
│   │   └── AppDependencies.swift
│   ├── Features/Checkout/
│   │   ├── Views/CheckoutView.swift
│   │   ├── ViewModels/CheckoutViewModel.swift
│   │   ├── Models/
│   │   └── Data/CheckoutRepository.swift
│   ├── Services/
│   │   ├── Networking/
│   │   └── Persistence/
│   └── Resources/
│       ├── Assets.xcassets/
│       └── Localizable.xcstrings
└── ShopTests/Checkout/
```

UIKit 项目可在 `App/` 放生命周期入口，在 `Views/` 放视图控制器和视图。
