# Graphify 单任务上下文与审计

## 何时启用

| 任务用途 | 创建选项 | 生成阶段 |
| --- | --- | --- |
| 修改既有代码，需要调用链、契约或流程上下文 | `--graphify-context` | before + after |
| 不需要前置图，但交付需要拓扑和调用流程审计（包括纯新增） | `--graphify-audit` | 仅 after |
| 文档、无关源码的任务 | 不传上述选项 | 不生成、不加载 |

选项互斥。是否使用图在任务创建和确认前决定；不能在实施中借建图扩大允许范围。每项以可独立验收的行为为颗粒度，跨仓库依赖记录为外部边界并另拆任务。不自动安装 Graphify，不启动服务，不建立整仓图。

## 范围与任务材料

两种模式都在任务 Markdown 填写精确仓库相对路径，不接受目录、通配符、符号链接、仓库外路径、密钥或 vendor/构建目录。

```markdown
## 修改范围

- MODIFY src/payment.py — 修改支付返回值
- CREATE tests/test_payment.py — 增加验收
- DELETE src/obsolete.py — 删除废弃实现

## Graphify 与只读证据范围

- GRAPHIFY_INPUT src/storage.py — 核对支付存储契约
- READ_ONLY_EVIDENCE docs/payment.md — 业务规则依据

## 流程变化与确定编码上下文

当前流程 → 目标流程 → 保留行为。列出触发条件、判断、调用与副作用、错误、
模块职责、契约、规则/示例、验收入口、编码限制和未解析依赖。
```

可编辑源码自动入图，不重复列入 GRAPHIFY_INPUT；没有额外依赖时该列表可以为空。只读证据只参与指纹，不送入 AST。可编辑非源码文件做权限与指纹检查，不送入图；显式 GRAPHIFY_INPUT 必须是支持的源码。没有可分析源码时报告阻塞，不制造空图。

before 模式还需填「Graphify 依赖证据」：查询问题、关键边、原仓库 `path:line`、EXTRACTED / INFERRED / AMBIGUOUS 标签及源码核验。图里的关系不是业务结论，动态注册、反射、配置和远端调用需要另外取证。

## 修改前生成与按需加载

以下 `flow` 代表 `python3 /path/to/AIWorkflow/workflow.py`，在目标 Git 业务仓库执行：

```sh
flow add payment T01 --title "调整支付结果" --example E01 --graphify-context
# 补齐任务范围和材料。
flow graphify payment T01
flow audit payment T01
```

`status` / `audit` 显示本任务的精确图路径。查询时始终指定这个路径；不要使用默认整仓 `graphify-out/graph.json` 或其他任务的图。先提出一个具体问题，再查询相关部分，不把完整图加载进对话。

```sh
graphify query "支付请求如何调用存储" --graph <本任务before图路径> --budget 2000 --depth 2
graphify path "Payment" "Storage" --graph <本任务before图路径>
graphify explain "Payment" --graph <本任务before图路径>
```

将结论核对源码后写回任务正文，再请负责人确认，执行 `flow confirm` 和 `flow start`。确认绑定任务正文、范围、示例、证据与 before 图；确认后相关输入变化需重建和重确认，无关文件不会使任务图失效。

发现依赖越过白名单，先 `flow block`，提出最小新增路径及读写理由；经负责人确认再修订范围，不自动递归扫描。

## 修改后审计

```sh
flow verify payment -- python3 -B -m unittest tests.test_payment
flow graphify payment T01 --phase after
flow audit payment T01
```

verify 仍只运行给定验证命令，不暗中建图。成功验证、生成 patch 且没有越界改动后才能生成 after。工具输出独立的 `audit.md` 和 `callflow.html`：

- 前后关系新增/移除，按源码路径、符号和关系类型比较，不依赖随机节点 ID；重复关系保留计数。
- 原生 Graphify 调用流程 HTML。它展示静态拓扑和代表性调用关系，不等于完整控制流图。
- 无 before 时明确注明“无前置图，不作关系差异断言”。
- 歧义节点、无法映射的关系明确列为限制，不以图中没有边证明无依赖。

Agent 读取本任务 `audit.md`，结合实际源码和测试填完六节：实际流程；条件、异常与副作用；保留行为；规则、示例与验证；源码核验；未解析边界。必要的业务流程分支图可在「实际流程」用 Mermaid 补充，标明依据。不能把计划当成已实现事实，也不能仅将“待核验”改成“完成”。

这些是交付材料，**不要为了写实际审计而改动已确认的任务正文**。填完后：

```sh
flow graphify payment T01 --phase after --seal
flow audit payment T01
flow audit payment T01 --diff
# 负责人核对报告、图、源码差异和验证结果后接受；Agent 仅可代记明确授权。
flow review payment T01 accept
```

seal 不重建图，只把已核验报告、图、HTML 与本次验证日志、checkpoint、patch hash 绑定。命令仅能检查必填材料和一致性，不能判定自然语言的业务结论是否真实；负责人仍需审阅。

图、报告、HTML、范围源码或只读证据变化时不能沿用已封存审计。重新 verify（包括对已通过任务的 `--task T01` 复验）后，需重新生成 after、核验并 seal，进入待审阅再接受。rework 不要求有效图，返工完成后重新走验证与后置审计。

## 仅后置审计与不建图

纯新增且无需前置代码图时：

```sh
flow add payment T02 --title "新增独立校验器" --example E02 --graphify-audit
# 填写 CREATE 路径、设计、边界与验收；无需先建图。
flow confirm payment T02 --statement "<负责人确认原话>"
flow start payment T02
# 实现后，按上面的 verify → after → 核验报告 → seal → review 流程交付。
```

不需要图的文档任务：正常 `add`，不传任何 Graphify 选项，继续原有 confirm/start/verify/review 流程。

## 证据隔离与兼容

产物保存在 `.ai-workflow/<需求>/graphify-scope/<任务>/<before|after>/build-*/`，每次从干净镜像生成。旧产物不覆盖，失败不登记为可用图，也不清理其他任务文件。默认不进入 Git。

before 包含待删除源码、不包含尚未创建的文件；after 包含新建源码、排除已删除文件。前置图是历史基线，完成任务后不要求源码恢复原样，依赖任务检查已接受的交付并用自身范围核对当前输入。

已有 version=1 任务和旧 manifest 仍可读取，不自动增加 after 门槛；未启用图的任务也不改变。新建带图任务使用 version=2。范围检查只是验收门槛，不是文件系统沙箱。路径名过滤无法识别伪装成普通源码的秘密，提交范围前仍须检查内容。

生成 HTML 不代表浏览器渲染已验证；Graphify 导出可能引用外部前端脚本，离线或受限网络环境需检查渲染。图也不替代真实测试、运行时取证或人工业务审阅。
