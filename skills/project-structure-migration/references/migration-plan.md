# 迁移清单

清单只描述一个基准提交下的一批改动。复制模板后替换示例值。联动文件按实际引用填写。

| 字段 | 内容 |
|---|---|
| `base_commit` | 规划时的完整 Git 提交 SHA |
| `module` | 本批模块或可以独立验证的文件组 |
| `moves` | 每项填写 `from`、`to` 和 `reason`，依据注明规范文件及规则或项目例外 |
| `linked_edits` | 必须联动修改的现有文件路径，按实际引用逐项列出 |
| `linked_edit_notes` | 以路径为键，说明每项联动修改的理由 |
| `verification` | 现有构建、测试命令及适用范围 |
| `undecided` | 按 `path`、`reason` 记录未确定归属的文件，本轮维持现状 |

路径以仓库根目录为基准，使用 `/` 并保留实际大小写。清单文件建议放在仓库外，以免进入本批次的路径差异。

## 脚本用法

需要 Git 和 Python 3.8 或以上。在源仓库中运行。若 Skill 位于其他位置，使用脚本的实际路径。

```sh
python3 .agents/skills/project-structure-migration/scripts/check_paths.py preflight /absolute/path/batch.json
python3 .agents/skills/project-structure-migration/scripts/check_paths.py verify /absolute/path/batch.json
```

- `preflight` 使用基准提交上的干净工作树，检查已跟踪的源文件、目标路径、大小写碰撞和联动文件。
- `verify` 检查基准后的提交、暂存区、工作区和未忽略的未跟踪文件所体现的路径范围，并核对移动及联动文件。未填写必要改动或少做了联动修改时，应修正清单或实际改动。
- 脚本检查的是路径与 Git 差异。引用语义、构建、测试和被 Git 忽略的内容，需要结合项目检查。命令由仓库约定提供，脚本仅读取 Git 和文件系统。
- 仅大小写或 Unicode 形式变化的重命名、符号链接、同批路径链式改名及子模块内部迁移需要单独核查。无可靠脚本覆盖时记录原因，并用项目自身的 Git 差异与构建测试验收。
