---
name: ai-workflow
description: Use when a coding task or business behavior change is being handled through AIWorkflow, or an existing AIWorkflow task needs resuming or review.
---

# AIWorkflow

在业务 Git 工作区运行 `python3 <本技能所在仓库>/workflow.py`，下文简称 `flow`。项目业务规则继续跟项目代码走。

## 任务颗粒度规则

拆分、执行或续接任务时，读取 [AI 规范与任务颗粒度规则](../../docs/ai-task-granularity-rule.md) 第 3–4 节。组织项目规范时读取第 1–2 节，评估 Skill 效果时读取第 5 节。此路径相对于本 `SKILL.md`，在业务仓库中调用时也从 AIWorkflow 仓库读取。

## 编码规则按需加载

进入编码、API 设计、文件归属规划或代码审查时，读取 [通用规则加载索引](../../docs/coding-rules.md)，按当前任务受影响文件、实际技术栈和阶段选择规则。目录规范、Swift 和 Objective-C 规范由 AIWorkflow 提供，不要求用户额外安装每项 Skill 或把文档复制进业务仓库；不加载整个规范目录。

从本主 Skill 的真实文件位置解析 AIWorkflow 根目录，不从业务 cwd 或固定机器路径查找。确认前在任务「适用规范」记录资源引用、适用原因/章节、阶段和项目例外；编码前与续接时读本阶段所需内容，验收按同一组规则审查。已有会话中已读取且仍适用的规则不必机械重读；缺少上下文时重新读取。

业务仓库明确约定、兼容性与构建要求优先，冲突说明依据，不借通用规范扩大改动范围。通用规范与 Graphify 业务证据分开，不把外部规范加入 GRAPHIFY_INPUT/READ_ONLY_EVIDENCE。加载依靠 Agent 执行本 Skill 指令，不是 CLI/Pi 强制注入，不能据记录声称规则已正确执行。

## 接入 Superpowers

先初始化需求并设置下方的审计上下文。再从当前 Agent 已加载的技能目录读取并使用 **Superpowers 原版** `brainstorming` 和 `writing-plans`。在 Pi 中用技能列表提供的文件路径读取 `SKILL.md`。无法找到任一上游技能时说明缺哪项，让用户加载 Superpowers 后再继续该阶段。不要用自己概括的流程冒充已加载上游。续接已有任务时，先看 `flow status <需求ID>`；只有回到需求澄清或规划时才重新加载对应技能。

本工作流的产物位置和执行交接约定如下。以它们作为本次任务的约束：设计和计划草稿放在 `.ai-workflow/<需求ID>/`，无需为设计、计划或任务进度创建 Git 提交。采用 AIWorkflow 的执行交接，跳过上游建议的独立执行器交接和进度文件。人工确认之后，执行交给 `flow start` 和 `flow verify`。适用时可用原版 `test-driven-development` 指导当前任务内的测试和实现。任务进度只在 `tasks.md` 中推进。

## 声明 Skill 并设置审计范围

先在对话里简述要用哪些 Skill、分别用于哪一步，以及准备怎样验收。用 `flow skill <需求ID> <技能名> --stage clarify|plan|execute|verify --purpose <用途>` 记录声明。任务阶段加 `--task T01`，有对应产物时加 `--evidence <路径>`。临时新增的 Skill 同样记入。只有 Pi 观察扩展可以登记 Pi 观察来源。

若当前 Pi 提供 `ai_workflow_audit_context`，初始化需求后、读取上游技能前，先设为 `clarify`，进入整体规划时改为 `plan`。每次进入单任务执行或验收时切换阶段并传任务编号。重开会话后重新设置。自动观察证明确实发生了读取或调用，业务结果仍由回执中的产物和验证判断。

## 用 Example Mapping 澄清并确认设计

用 `flow init <需求ID> --goal <目标>` 创建 `examples.md` 和 `tasks.md`。以 Superpowers `brainstorming` 组织对话。先查相关代码、测试和项目约定，再把澄清结果写成 Cucumber Example Mapping 的四部分：

- **故事**写需求来源、想达到的结果及已证实的当前行为。
- **规则**一行一个编号，例如 `- R01: 同一键只产生一次扣款`。注明规则依据或待确认的假设。
- **示例**引用规则，例如 `- E01 [R01]: 给定已扣款，同键同金额重试，返回首次结果且扣款次数仍为一`。按风险补上边界和回归例。
- **未决问题**引用受影响规则，例如 `- [ ] Q01 [R01]: 同键不同金额时怎么响应？`。跨规则阻塞写 `[*]`。有人确认后，用 `- [x] Q01 [R01]: 同键不同金额时怎么响应？ 决定：拒绝且不扣款` 记录。Agent 可继续取证，业务决定交给负责人。

用上游技能比较适用的实现选项，让负责人确认目标示例、需要保留的行为和设计取舍。需要书面设计时保存在本需求目录。信息已充分的小变更可以在对话里确认设计。澄清阶段只读调查业务代码。

## 用 Superpowers 拆分并交接到任务文件

读已确认的 Example Mapping 和设计，按原版 `writing-plans` 拆成独立可验收的任务。若该技能需要一份完整草稿，放在本需求目录的 `plan-draft.md`，只用于整理。以 `flow add <需求ID> T01 --title <可观察结果> --example E01` 建立任务。多场景可重复传 `--example`，真实依赖用 `--after T01`。只读调查可以使用 `--investigation`，输出应是可复用的证据或复现。

把业务澄清、模块职责、实现步骤、改动上下界和具体验收写入对应的单任务文件。涉及代码/API 或文件归属时，按通用规则索引选择并填写本任务「适用规范」；不适用时写明原因，不为凑记录加载无关资源。每项能用自己的测试或验证证明结果。负责人确认整体拆分时，可一并确认已经澄清的任务。用 `flow confirm` 逐项记录明确确认的原话。关键歧义仍未关闭的任务暂缓，独立且已确认的任务可以继续。正式的执行计划和进度以任务清单与单任务文件为准。

## 按需使用 Graphify

按当前任务用途选择，不因技术栈或整仓存在源码就加载图：

- 修改既有代码且需调用链、共享契约或流程上下文：`add --graphify-context`，生成 before，上下文核对后确认开工；交付另生成 after。
- 不需要前置图，但交付需要拓扑与调用流程审计：`add --graphify-audit`，仅生成 after，纯新增代码也适用。
- 不需要代码关系图的任务：不启用、不生成、不加载。

启用时先读 [单任务 Graphify 操作与边界](../../docs/graphify-task-lifecycle.md)，按精确路径填写修改范围、只读输入与证据、流程变化和编码边界。before 额外记录依赖查询、源码位置及 EXTRACTED / INFERRED / AMBIGUOUS 核验结论。

先读 `status` / `audit` 的本任务产物摘要；查询必须传 `--graph <本任务对应阶段图路径>`，从 `query --budget 2000 --depth 2` 起步，只加载当前问题相关结果，不读整仓图或其他任务图。发现范围外依赖、图缺口、动态依赖未解释时先记录阻塞并申请最小范围修订，不能由“没有边”断言无依赖。图不代替源码、测试或业务判断。

## 逐项执行与续接

- 先从 `flow status <需求ID>` 定位当前任务，再读该任务文件、它引用的示例和必要的依赖证据；按「适用规范」解析 AIWorkflow/项目引用，加载当前阶段所需条款。旧任务缺少该节时先判断适用规则；补写已确认正文需暂停并重确认。用 `flow start <需求ID> T01` 开工，编码前完成适用规则加载。实现时核对实际差异与边界。
- 当前任务需要写入或修改代码时，先设置本任务的 `execute` 审计上下文，再于动手前读取 [Ponytail 编码规则](references/ponytail/SKILL.md)。在已确认的任务范围内使用其 “Before you write” 和 “The smallest complete change” 两节（Full）。优先复用项目现有实现，选择完整满足验收的最小改动，保留必要的校验、错误处理和可访问性。任务边界、仓库约定和验证仍按现有工作流执行。读取后用 `flow skill <需求ID> ponytail --stage execute --task T01 --purpose "应用最小完整改动规则"` 声明，并用 `--evidence` 附上模板的实际路径。
- 用 `flow verify <需求ID> -- <验证命令及参数>` 记录实际测试和回归结果。新建的带图任务验证成功后，用 `flow graphify <需求ID> T01 --phase after` 生成本次拓扑/调用流程及独立审计报告；按源码、规则/示例和测试补齐报告的实际流程、条件/异常/副作用、保留行为、核验及未解析边界，再用同命令加 `--seal` 绑定本次验证。不要为写实际审计而修改已确认任务正文，不把调用图当完整控制流证明。
- 用 `flow audit <需求ID> T01` 展示适用规范、范围、实际差异、图/报告与验证结果；按本任务记录的规则核对本次 API、文件归属和项目例外，请负责人审阅后用 `flow review <需求ID> T01 accept|rework` 记录判断；仅经明确授权代记原决定。接受后再推进。必要时用 `flow verify <需求ID> --task T01 -- <命令>` 复验；带 after 门槛的任务须刷新后置审计再接受。旧 version=1 和无图任务保持原流程。
- 缺口用 `flow block` 记录。业务决定用 `decision`，取证缺口用 `evidence`，外部条件用 `external`。后两类补齐后用 `flow resolve`。业务决定由负责人确认后再登记 `flow confirm`。
- 新的业务想法从当前代码和测试重新走一个聚焦需求。同一轮其余已确认且不受影响的任务沿用。交付后本地工作状态可清理，长期业务约束由项目代码、测试和现行规范承载。
