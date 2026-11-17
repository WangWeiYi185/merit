---
name: swift-api-design-guidelines
description: 编写、修改或评审 Swift API、类型、协议、方法、参数标签与文档注释时使用。依据 Swift 官方 API Design Guidelines，以调用处清晰为首要目标；适用于 Swift Package、公共模块与业务内部 API，不代替架构、并发或 UI 专项规范。
---

# Swift API 设计与编码规范

## 来源与边界

- 官方来源：https://www.swift.org/documentation/api-design-guidelines/
- 本 Skill 是官方指南的中文操作化整理，不是完整 Swift 编码风格标准。
- 官方涵盖 API 命名、参数、惯例与文档；不据此宣称缩进、行宽、文件组织、架构、错误处理策略或并发方案有官方强制要求。
- 项目已有格式化、兼容性和业务契约继续生效；冲突时说明差异，不擅自改契约。
- 本文示例是命名示意，不是可直接编译的完整程序；不为业务默认值、状态或公式提供依据。

## 执行流程

1. **明确范围**：读取目标文件、相邻 API、调用点和相关测试，确认访问级别、协议实现、跨模块及 Objective-C 暴露边界。
2. **先写调用处**：至少给出一个典型调用；有歧义时再给一个边界调用。不能只看声明判断命名优劣。
3. **逐项设计**：检查语义、名称、标签、副作用、默认参数、重载和文档，遵循下方规则。
4. **最小修改**：只修改本次目标；已有外部调用、协议要求或序列化字段不能为“统一风格”直接破坏。公开 API 重命名须说明兼容影响，必要时提出迁移方案，获授权后实施。
5. **验证与报告**：搜索受影响调用、补充适当测试，按项目规则运行验证。未编译不得声称编译通过；不要为纯命名评审自动触发全量构建。

## 1. 基本原则（Fundamentals）

- **调用处清晰优先**：声明只写一次，调用会反复出现。
- **清晰胜过简短**：不要以最少字符数为目标。
- **为每个声明编写文档注释**：这是官方原则，不应被缩减为“只有 public 才需要”。实际修改聚焦新增和受影响声明，不以此要求全仓补注释。
- 若无法用简单语言说明 API，先检查设计本身，不用长篇注释掩盖语义问题。

## 2. 命名：明确、自然、符合术语（Naming）

### 消除歧义，去掉无效词

- 保留区分语义所需的词：`remove(at: index)` 表示按位置删除，`remove(element)` 表示按元素删除。
- 去掉只重复类型信息的词：在语义明确时用 `remove(_:)`，而不是 `removeElement(_:)`。
- 变量、参数和关联类型按**角色**命名：`greeting` 优于 `string`，`supplier` 优于 `widgetFactory`，`ContentView` 优于 `ViewType`。
- `Any`、`AnyObject`、`NSObject`、`Int`、`String` 等类型不能充分表达角色时，补足名称或标签，例如 `addObserver(_:forKeyPath:)`，不要机械删除“看似重复”的词。

### 按使用语法与副作用命名

- 调用尽量构成自然英语：`insert(item, at: index)`、`distance(to: destination)`。
- 工厂方法以 `make` 开头，如 `makeIterator()`。
- 初始化器与工厂方法不要刻意让首参数与基础名称拼成短语：用 `Color(red:green:blue:)`、`makeWidget(gears:spindles:)`，不用 `Color(havingRGBValuesRed:...)`。
- 无副作用的方法读作名词短语；有副作用的方法读作祈使动词短语，如 `distance(to:)` 与 `sort()`。
- 原地修改与返回新值成对命名：

| 原地修改 | 返回新值 |
| --- | --- |
| `sort()` | `sorted()` |
| `reverse()` | `reversed()` |
| `stripNewlines()` | `strippingNewlines()` |
| `formUnion(_:)` | `union(_:)` |

优先使用过去分词 `-ed`；动词带直接宾语、不适合过去分词时用 `-ing`；天然是名词的操作，为修改版本加 `form`。

- 非修改型 Bool 属性或方法在调用处读作对接收者的断言，如 `isEmpty`、`intersects(_:)`；不是所有 Bool 都必须机械加 `is`。
- 表示“是什么”的协议用名词，如 `Collection`；表示能力的协议用 `-able`、`-ible`、`-ing`，如 `Equatable`、`ProgressReporting`。
- 其他类型、属性、变量和常量通常用名词。

### 术语与大小写

- 优先常用词；专业术语必须符合已有精确定义，不重新发明含义。
- 避免非标准缩写；遵循领域先例，例如 `sin` 不应被冗长描述替代。
- 类型和协议用 `UpperCamelCase`，其他名称用 `lowerCamelCase`。
- 惯用全大写缩略词按位置保持整体大小写，如 `utf8Bytes`、`UTF8`、`userSMTPServer`、`isRepresentableAsASCII`；已词汇化的缩写按普通单词处理，如 `RadarScanner`。

## 3. 参数与标签（Parameters / Argument Labels）

### 参数名与默认值

- 内部参数名为文档服务，外部标签为调用处服务，可以不同：

```swift
/// Moves from `start` to `end`.
func move(from start: Point, to end: Point)
```

- 只有存在明确、常用且符合契约的值时才提供默认参数；不能凭风格偏好编造 `0`、`false`、`nil` 或业务阈值。
- 通常优先默认参数，而不是大量仅少几个参数的重载；默认参数尽量后置，并保留标签。
- 生产 API 的源位置参数优先 `#fileID`，减少路径泄漏与体积；仅开发工具、测试或文件操作确实需要完整路径时用 `#filePath`；需兼容 Swift 5.2 或更早版本时考虑 `#file`。

### 标签决策顺序

1. **参数无法有意义地区分**：可省略所有标签，如 `min(x, y)`、`zip(xs, ys)`。
2. **保值类型转换初始化器**：省略首标签，如 `Int64(someInt32)`；源值是第一参数。缩窄、截断等转换应通过 `truncating:` 等标签明确语义。
3. **首参数构成介词短语**：标签通常从介词开始，如 `remove(at:)`、`removeBoxes(havingLength:)`。
4. **多个参数组成一个抽象**：把介词放到基础名称，避免只修饰第一个分量，如 `moveTo(x:y:)` 而非 `move(toX:y:)`。
5. **首参数直接参与正确的语法短语**：省略首标签，如 `addSubview(view)`。
6. **其他情况**：首参数保留标签，如 `dismiss(animated: false)`，不要写成含义不明的 `dismiss(false)`。
7. 除上述明确例外，后续参数都加标签；有默认值的参数应有标签。

“读起来通顺”还不够，必须表达正确动作；不要把 Bool、数量等误读成动作对象。

## 4. API 惯例与歧义（Conventions / Special Instructions）

- 非 `O(1)` 的计算属性要在文档中标明复杂度，不让调用方误以为是廉价存储属性。复杂度依据实现分析，不能猜测。
- 优先方法或属性；自由函数适用于没有明显接收者（`min`）、不受约束的泛型（`print`），或领域惯用记法（`sin`）。
- 同名重载应共享基本语义，或属于不同领域；不要让同一个 `index` 同时表示“重建索引”与“读取某行”。
- 避免只通过返回类型区分重载，以免类型推断歧义。
- API 暴露的元组成员要命名；闭包类型中的参数也要命名以支持理解和文档：

```swift
func ensureStorage(
    allocate: (_ byteCount: Int) -> UnsafeMutableRawPointer
) -> (reallocated: Bool, capacityChanged: Bool)
```

闭包参数名不是调用处标签；不要生成不合法的闭包实参标签语法。

- 对 `Any`、`AnyObject` 或无约束泛型的重载额外检查歧义，尤其是“单元素”与“序列内容”：

```swift
values.append([2, 3])             // 添加一个数组元素。
values.append(contentsOf: [2, 3]) // 逐个添加序列中的元素。
```

不要只依赖参数类型区别这两种意图；在 `[Any]` 等上下文中检查调用含义。

## 5. 文档注释规范（Documentation Comments）

使用 `///` 与 Swift Markdown。摘要最重要：尽量一个以句号结尾的句子片段，先说明语义，不重复声明。

- 函数/方法：做什么、返回什么；不解释空操作或 `Void` 返回。
- 下标：访问什么。
- 初始化器：创建什么。
- 其他声明：是什么。
- 详细讨论与摘要空一行；详细段落可使用完整句子。
- 按需使用 `Parameter`、`Returns`、`Throws`、`Precondition`、`Postcondition`、`Complexity`、`Warning`、`Note`、`SeeAlso` 等标记；不要为了填模板捏造约束。

```swift
/// Removes and returns the element at `position`.
///
/// - Parameter position: The index of the element to remove.
/// - Returns: The removed element.
/// - Precondition: `position` is a valid index in the collection.
mutating func remove(at position: Index) -> Element
```

上述前置条件仅适用于确实要求有效下标的实现。对实际使用 `throws`、可选返回或其他错误机制的 API，应如实记录其契约。

## 6. 评审清单与输出

交付前检查：

- [ ] 已阅读真实调用处，名称可直接理解且无无效词。
- [ ] 名称表达角色、副作用、修改/非修改关系及正确领域术语。
- [ ] 标签按语义选择，弱类型参数、Bool 和数量不存在歧义。
- [ ] 默认值有既有契约依据，没有新增隐式业务决定。
- [ ] 重载不依赖返回类型，无约束泛型下也不混淆单值与序列。
- [ ] 新增或受影响声明有准确摘要；非恒定时间计算属性记录复杂度。
- [ ] 公开 API、协议、Objective-C 调用与其他消费者的兼容影响已检查。
- [ ] 验证结果与未验证项如实区分。

评审仅输出适用项，建议格式：

```text
位置：文件路径:行号
问题：调用处的具体歧义或不符合项
依据：官方指南章节与规则
建议：修改前/后的声明与典型调用
影响：消费者、兼容性与需要的验证
```

区分“官方指南建议”“项目约定”“个人偏好”，不要把个人偏好报告为官方违规；对已有契约明确、修改收益不足的名称，可保留并说明理由。
