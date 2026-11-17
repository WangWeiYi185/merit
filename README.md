# AIWorkflow

用于 Pi 和其他 Coding Agent 的本地工作流。使用 Cucumber Example Mapping 澄清需求，调用 Superpowers 上游技能做设计和计划。清单保存顺序和状态，单任务 Markdown 保存当前任务需要的业务及技术上下文。

## 使用方式

需要 macOS 或 Linux、Python 3.11+ 和 Git。无需安装 Python 依赖。在**目标业务仓库**运行命令，`flow` 在下面的例子中代表本仓库的 `workflow.py`。

```sh
flow() { python3 /path/to/AIWorkflow/workflow.py "$@"; }
flow init payment-retry --goal "澄清并实现支付重试"
# 先在 .ai-workflow/payment-retry/examples.md 添加规则 R01 和示例 E01。
flow add payment-retry T01 --title "相同金额重试返回首次结果" --example E01
flow status payment-retry
```

在 Pi 安装 [Superpowers 上游包](https://github.com/obra/superpowers#pi)，然后在目标业务仓库加载 AIWorkflow：

```sh
pi install git:github.com/obra/superpowers
pi --skill /path/to/AIWorkflow/skills/ai-workflow/SKILL.md \
   -e /path/to/AIWorkflow/extensions/ai-workflow-audit.ts
```

进入 Pi 后用 `/skill:ai-workflow <需求描述>` 启动。AIWorkflow 读取已安装的 Superpowers `brainstorming` 和 `writing-plans`，把结果接入本地示例和任务文件。其他 Agent 可加载同一份 [工作流指令](skills/ai-workflow/SKILL.md) 及对应的上游技能。Example Mapping 使用 Markdown，无需安装 Cucumber 测试运行器。

语言编码规范可按需单独加载：[Swift API 设计指南](skills/swift-api-design-guidelines/SKILL.md) 和 [Objective-C Cocoa 编码与 API 约定](skills/objective-c-cocoa-guidelines/SKILL.md)。它们补充语言层面的 API 设计与编码建议，不替代业务仓库自身的 `AGENTS.md` 和项目约定。

实现代码时，AIWorkflow 会按任务读取 [Ponytail 编码规则](skills/ai-workflow/references/ponytail/SKILL.md)，用它约束实现规模和代码复用，并在对应任务记录 Skill 使用。模板与 [MIT 许可](skills/ai-workflow/references/ponytail/LICENSE) 随仓库保存。[上游固定版本](https://github.com/DietrichGebert/ponytail/blob/96608e078b2d5ea607c5c3b8b5a54d1c1fba6846/skills/ponytail/SKILL.md)

## 从需求到交付

1. Agent 只读调查源码、业务规则和测试。按 [Example Mapping](https://cucumber.io/docs/bdd/example-mapping/) 填写故事、规则、示例和未决问题，再用 Superpowers 确认设计、拆分任务。空任务模板会在确认时提示缺失字段。

需要追踪源码调用链、模块依赖、共享契约或代码驱动流程的任务，用 `flow add ... --graphify-context` 启用任务级 Graphify 上下文。任务文件须列出精确 `EDITABLE`、`GRAPHIFY_INPUT` 和 `READ_ONLY_EVIDENCE` 路径；补齐源码依赖证据、业务流程变化和编码边界后运行 `flow graphify <需求ID> T01`。工具仅镜像列明的源码，确认时绑定范围与图的指纹，开工前检查新鲜度，验收时阻止越界改动。纯文档等不调查源码的任务不需要启用。详细格式和限制见 [AIWorkflow Skill](skills/ai-workflow/SKILL.md)。
2. 负责人用具体表述确认**当前行为、这次改动、应保留行为和验收方法**。如果已在聊天里确认，Agent 可以原样记录。
3. 启动一项，实施后核对实际差异并运行这一项的验证。验收应覆盖目标行为及相关旧行为。
4. 新需求验证通过后进入待审阅，负责人接受后才可以开始依赖任务。遇到缺口先记录，等能解决的人补齐。交付后按需清理本次需求目录。

```sh
flow confirm payment-retry T01 --statement "目前重复请求返回冲突。本次只允许同键同金额返回首次结果，保留只扣款一次。先用支付重试测试验证。"
flow start payment-retry T01
flow verify payment-retry -- python3 -m unittest tests.test_payment_retry
flow audit payment-retry T01
flow audit payment-retry T01 --diff
flow review payment-retry T01 accept
flow status payment-retry
```

验证命令请替换为项目实际入口。若命令需要生成文件，将它们输出到项目已忽略的位置。CLI 记录命令、退出码、日志及对应工作区标识。验证期间若跟踪或未忽略的文件发生变化，任务保持执行中。标识用于比对状态，要保留可恢复的代码版本时，可在验证前按项目约定保存本地提交。验证命令是否真正覆盖业务验收由负责人和 Agent 核对。工作区状态和前置验证不同时，启动会提示核对。若前置任务的相关输入有变，在没有执行中任务时用 `flow verify <需求ID> --task T01 -- <命令>` 复验。复验失败会将该任务退回待执行。

### Example Mapping 格式

```markdown
## 规则
- R01: 同一幂等键只扣款一次。

## 示例
- E01 [R01]: 相同金额重试返回首次结果，扣款次数仍为一。

## 未决问题
- [x] Q01 [R01]: 同键不同金额时如何响应？ 决定：返回冲突且不得再次扣款。
```

用 `- [ ]` 标记未决问题，`[*]` 表示影响全部规则。相关问题会阻止任务确认及开工。确认只绑定已引用的规则、示例和相关决定，其他例子的更新可以独立进行。若已通过任务引用的内容变了，依赖任务会暂停。对受影响的前置任务重新确认并验证后即可继续。只读取证可用 `add --investigation`。已有且没有 `examples.md` 的本地需求可继续使用旧格式。

### 阻塞和需求变动

```sh
flow block payment-retry --kind evidence --issue "缺少扣款次数证据" --impact "无法验收幂等" --next "定位可观察的调用入口"
flow resolve payment-retry T01 --detail "已有支付测试能观察扣款调用"
```

也可以用 `block --task T01` 记录尚未开工的缺口。`decision` 需要负责人再次确认，`evidence` 和 `external` 可在补齐后使用 `resolve`。需求发生变化时，停下冲突任务、保留现有修改，用新的需求 ID 从当前事实基线开始，并保留本轮其余已确认任务。

## 审计和首次交付接受率

- 开工前声明 Skill 及用途。例如 `flow skill payment-retry brainstorming --stage clarify --purpose "澄清重试行为"`。阶段可选 `clarify`、`plan`、`execute`、`verify`。单任务记录用 `--task T01`，可用 `--evidence` 链接产物。
- 加载上面的 Pi 扩展时，Agent 会设置当前需求、阶段和任务。扩展记录在该上下文中 **Pi 观察到的** Skill 命令展开及原生读取工具对已注册 Skill 文件的成功读操作。其他方式加载、扩展未运行或未绑定上下文时，仍使用声明记录。观察只代表调用或读到文件，业务执行效果靠实际产出与验证判断。这些是可编辑的本地记录，来源标签用于区分记录途径。
- `flow audit payment-retry T01` 给出本项允许范围、实际改动、验证结果及 Skill 记录。加 `--diff` 查看本地 Git 差异。差异从任务首次开工时的工作区生成，涵盖跟踪和未忽略文件。已有未提交的内容作为基线保存，不会修改业务仓库的 Git 索引。Git 规范化后没有出现在 diff 中的文件改动会单独提示。提交人核对变更是否符合范围。
- `flow review payment-retry T01 rework --note "原因"` 记录返工。首次审阅结论固定计入 `flow audit payment-retry` 的唯一统计，首次接受的任务数 ÷ 已审阅任务数。返工后再次接受不会改变首审结果。工作区与本次证据不一致时，重新验证再审阅。
- 已经开工且没有审计基线的旧任务沿用原流程。新需求默认带审计，可在交付后清理本地证据。

## 本地状态和控制边界

```text
.ai-workflow/<需求ID>/
  examples.md
  tasks.md
  tasks/T01.md
  T01-*.log
  audit/                    # 本地 Skill 记录和任务差异
```

本地目录内的忽略规则使这些文件默认不进入 Git。清单的任务表和任务文件的「工作流记录」由命令维护，其他段落可直接编辑。新会话读取清单和当前任务，按需读取项目规则、代码以及依赖任务的验收结果。这个首版约束工作流命令的流转，编辑器和 shell 的写入仍使用各自权限。

## 测试

```sh
python3 -B -m unittest discover -s tests -v
```
