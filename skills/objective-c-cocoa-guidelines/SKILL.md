---
name: objective-c-cocoa-guidelines
description: Use when writing, modifying, or reviewing Objective-C code, especially Cocoa/UIKit APIs, public headers, classes, protocols, selectors, properties, or error handling; follow Apple Cocoa conventions alongside repository rules.
---

# Objective-C Cocoa 编码与 API 约定

## 来源与边界

- 主要参考：[Apple Coding Guidelines for Cocoa](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/CodingGuidelines/) 和 [Objective-C Conventions](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/Conventions/Conventions.html)。这是 Apple 的归档文档，适合作为 Cocoa 命名与惯例参考；遇到平台版本差异时，以目标 SDK 文档和仓库中的现行用法为准。
- 这些约定不替代仓库的 `AGENTS.md`、架构文档、格式化工具或业务契约。不要为统一风格而擅自改变公开行为、序列化字段或跨模块接口。
- 区分 Apple 建议、项目约定和个人偏好；不要把偏好报告为规则。

## 工作方式

1. 阅读目标声明、实现、调用点、相邻头文件和仓库规则，确认 API 是内部还是公开、消费者有哪些、最低系统版本是什么。
2. 从典型调用处检查命名和语义。若只看声明无法判断，写出一两个调用示例再评估。
3. 做最小必要改动。公开 API 或协议的重命名、签名变化和行为变化需检查源码/二进制兼容影响；保留兼容性时遵循仓库既有的废弃与迁移方式。
4. 检查受影响调用和适用的构建或测试；只报告实际执行的验证。

## 命名与接口形状

- 类、协议、枚举和全局符号使用项目约定的唯一前缀；Cocoa 传统上给类和全局符号加前缀，方法不加。不要使用 Apple 保留的两字母前缀；遵循仓库现有三字母前缀。
- 类型名用能表达角色的名词。方法名用清楚的动词或动作短语，属性名表达值或状态；避免含混缩写和无意义的类型重复。
- Selector 要结合冒号和实参一起读。参数标签应说明该参数在动作中的作用，例如 `insertObject:atIndex:`；多个参数的关键词要形成清楚、连贯的短语。
- 读访问器按 Cocoa 习惯表达值，写访问器使用 `set` + 属性名；布尔属性沿用项目习惯，通常采用 `isEnabled` 这类能自然读出的名称。不要为“统一”随意改动 KVC/KVO 可见的访问器。
- 初始化器通常采用 `initWith...`，工厂方法采用能说明产物的类方法名。遵循 Objective-C 的 `alloc`、`new`、`copy`、`mutableCopy` 家族命名语义，避免让自定义方法名意外承诺不符合预期的所有权行为。

```objc
@interface MRCWorkoutStore : NSObject

/// Inserts a workout at the requested position.
- (BOOL)insertWorkout:(MRCWorkout *)workout
              atIndex:(NSUInteger)index
                error:(NSError * _Nullable * _Nullable)error;

@end
```

示例仅展示命名和契约表达方式；实际返回值、空值策略与错误策略必须由真实实现和项目契约决定。

## 公开头文件与行为契约

- 头文件是调用者的契约。公开声明应准确表达用途、参数要求、返回值、失败方式、线程或生命周期约束（仅在确实适用时说明）。文档不要重复显而易见的声明，也不要编造限制。
- 新增引用类型 API 时，检查项目是否使用 `NS_ASSUME_NONNULL_BEGIN/END`，并明确标注真正可空的参数、属性和返回值；不要仅为消除警告把不确定值标成非空。
- 集合 API 在适合时使用轻量级泛型表达元素类型；枚举与位掩码遵循仓库对 `NS_ENUM` / `NS_OPTIONS` 的约定。
- 默认让可变状态留在实现内部。只有调用者确实需要时才公开写属性或可变集合；新增 API 不应泄漏实现细节。
- 错误处理服从现有 API 形状。Cocoa 常见约定是查找/创建对象失败返回 `nil`，执行操作通过布尔值和 `NSError **` 报告失败；不要在同一模块无理由混用异常、错误对象、状态码和断言。

## 修改和评审清单

- [ ] 典型调用处清楚表达动作、参数角色和结果，没有歧义或过度缩写。
- [ ] 类与全局符号前缀符合仓库约定，方法没有不必要前缀。
- [ ] 初始化、所有权、可空性、错误处理和可变性与实际实现一致。
- [ ] KVC/KVO、协议实现、子类覆写和现有调用点不因改名或签名变化意外破坏。
- [ ] 公开头文件注释描述真实契约；兼容性影响和验证结果如实说明。

评审时给出文件与行号、具体调用场景、问题、建议改法及兼容性影响。对已有且契约明确的 API，如果改名收益不足以抵消兼容代价，保留原名并说明原因。
