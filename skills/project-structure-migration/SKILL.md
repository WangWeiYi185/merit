---
name: project-structure-migration
description: Use when a user asks to plan or execute a bounded migration of existing repository files to standard project paths. Routine implementation and directory-tree summaries do not require this skill.
---

# 项目路径迁移

一次调用处理一个模式和一批可独立验证的文件。批次包含文件移动及其必要的引用修改。用户仅要求盘点或规划时，保持仓库只读。用户已提供清单并请求执行时，直接按清单执行。

## 按需读取

- 读取仓库适用的 `AGENTS.md`，再读取仓库指定的结构规范。采用本工具包时，从 `docs/project-structure.md` 选择本批技术栈的独立文档，已知具体路径时直接读取。目标路径以结构规范、项目例外和实际构建配置为依据。规范缺失或无法确定目标时，将文件记入待判断项。
- 仅在涉及 Xcode 工程或资源时，读取 [Xcode 检查项](references/ios.md)。
- 需要创建或理解交接清单时，使用 [清单模板](assets/migration-plan.json) 及 [字段说明](references/migration-plan.md)。

## 规划模式

1. 确认模块和基准提交。从指定模块及其直接相关的配置、引用开始定位文件。单次扫描可用文件名、路径和配置项缩小范围。
2. 输出一份清单。每个移动条目写明源路径、目标路径和归属依据，并注明结构规范文件及相关规则或项目例外。列出必须同步修改的文件及原因、验证命令和待判断项。多个可独立验证的模块给出各自的批次边界，本次只完成指定批次。
3. 对适用的 Git 批次运行只读 `preflight` 检查。任务内给出清单，或按用户指定位置保存。为保持仓库只读，可把清单保存在仓库外。

## 执行模式

1. 读取清单及其涉及的文件。对脚本覆盖的批次，按 [脚本用法](references/migration-plan.md#脚本用法) 运行 `preflight`。不受脚本支持的批次采用该参考中的替代检查。工作区已有改动时保留用户改动，可用同一基准的隔离工作树取得可归因的差异。
2. 仅移动清单列出的文件，并修改列出的联动文件。发现清单外的必要依赖时，列出新增路径、理由和当前状态。用户明确指定按这份清单执行时，把新增项作为清单修订建议，保持原清单的边界。用户已明确授权处理这些新增项时，先将它们写入清单，再继续执行。
3. 适用时运行 `verify`，检查 diff 中的引用及行为变化，再执行项目现有构建与相关测试。汇报实际路径、清单偏差、验证命令及结果。保留失败和未验证项。
