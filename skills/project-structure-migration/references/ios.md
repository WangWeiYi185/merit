# iOS 路径迁移检查

- 看实际项目如何登记文件。传统 Xcode group 可能在 `project.pbxproj` 中记录显式路径。同步目录要检查所属 target、同步根目录和例外项。使用 XcodeGen、Tuist 等生成工程时，应先定位项目生成配置以及仓库既有生成流程。
- 检查目标文件的编译或资源归属。Swift 文件关注 target 和模块。资源关注资产目录、String Catalog、字体及其他 Bundle 查找所用路径。迁移 Swift Package 内文件时检查 `Package.swift` 的 target 路径、资源和排除配置。
- 用仓库现有 scheme 和目的设备执行构建及相关测试。报告实际命令、结果以及无法执行的检查。
