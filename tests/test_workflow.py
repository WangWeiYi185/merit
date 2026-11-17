import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / "workflow.py"
SECTIONS = {
    "现状与依据": "当前支付流程及相关源码",
    "目标与示例": "相同金额重试返回原结果",
    "实现设计": "支付模块负责重试，使用现有存储",
    "最低交付": "返回首次支付结果",
    "最大范围": "仅修改支付重试逻辑",
    "保留行为与暂停条件": "保持只扣款一次，涉及共享接口时暂停",
    "验收方案": "验证首次结果和扣款调用次数",
}


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        (self.repo / "app.txt").write_text("before")
        self.git("add", "app.txt")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "baseline")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)

    def flow(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(CLI), *args], cwd=cwd or self.repo,
            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def ok(self, *args, **kwargs):
        result = self.flow(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def init(self, requirement, *, goal=None, audited=False):
        if goal is None:
            goal = "支付重试"
        self.ok("init", requirement, "--goal", goal)
        if not audited:
            (self.repo / ".ai-workflow" / requirement / "audit").rmdir()
        path = self.repo / ".ai-workflow" / requirement / "examples.md"
        self.assertTrue(path.is_file(), "init 应创建 Example Mapping 文档")
        path.write_text("""# 需求澄清

## 故事
付款人在重试时收到一致的结果。

## 规则
- R01: 同一幂等键只产生一次扣款。
- R02: 相同金额返回原结果。

## 示例
- E01 [R01]: 两次支付调用只发生一次扣款。
- E02 [R02]: 相同金额再次提交返回原结果。

## 未决问题

""")
        return path

    def task(self, requirement, task, after=None, example="E01"):
        args = ("add", requirement, task, "--title", "支付重试", "--example", example)
        self.ok(*args, *("--after", after) if after else ())
        path = self.repo / ".ai-workflow" / requirement / "tasks" / f"{task}.md"
        content = path.read_text()
        for heading, body in SECTIONS.items():
            content = content.replace(f"## {heading}\n\n", f"## {heading}\n\n{body}\n")
        path.write_text(content)
        return path

    def confirm(self, requirement, task):
        return self.ok("confirm", requirement, task, "--statement", "现在返回旧值。本次增加相同金额重试，保留只扣款一次。")

    def test_approval_and_sequential_verification(self):
        self.init("payment", goal="支付重试")
        first = self.task("payment", "T01")
        self.task("payment", "T02", "T01")
        self.assertIn("确认", self.flow("start", "payment", "T01").stderr)
        self.confirm("payment", "T01")
        self.confirm("payment", "T02")
        self.assertIn("前置", self.flow("start", "payment", "T02").stderr)
        self.ok("start", "payment", "T01")
        (self.repo / "app.txt").write_text("after")
        self.assertNotEqual(self.flow("verify", "payment", "--", sys.executable, "-c", "exit(1)").returncode, 0)
        self.assertIn("执行中", self.ok("status", "payment"))
        self.ok("verify", "payment", "--", sys.executable, "-c",
                "from pathlib import Path; assert Path('app.txt').read_text() == 'after'")
        self.assertIn("passed", first.read_text())
        self.ok("start", "payment", "T02")
        self.assertIn("T02.md", self.ok("status", "payment"))
        self.assertNotIn(".ai-workflow", self.git("status", "--short", "--untracked-files=all").stdout)

    def test_blocked_task_allows_independent_work_and_new_requirement(self):
        self.init("old", goal="旧目标")
        self.task("old", "T01")
        self.confirm("old", "T01")
        self.ok("start", "old", "T01")
        self.ok("block", "old", "--kind", "decision", "--issue", "缺业务决定", "--impact", "重试行为", "--next", "负责人确认")
        self.assertIn("需要人决定", (self.repo / ".ai-workflow/old/tasks/T01.md").read_text())
        self.assertNotEqual(self.flow("start", "old", "T01").returncode, 0)
        self.init("new", goal="修改目标")
        self.task("new", "T01")
        self.confirm("new", "T01")
        self.ok("start", "new", "T01")
        self.assertIn("阻塞", self.ok("status", "old"))

    def test_resolve_keeps_approval_for_unchanged_plan(self):
        self.init("example", goal="目标")
        self.task("example", "T01")
        self.confirm("example", "T01")
        self.ok("start", "example", "T01")
        self.ok("block", "example", "--kind", "external", "--issue", "缺测试环境",
                "--impact", "无法验证", "--next", "恢复依赖")
        self.ok("resolve", "example", "T01", "--detail", "环境已恢复")
        self.ok("start", "example", "T01")
        self.ok("verify", "example", "--", sys.executable, "-c", "assert True")
        self.assertIn("T01.md", self.ok("status", "example"))
        (self.repo / "app.txt").write_text("another change")
        self.assertIn("重验", self.ok("status", "example"))
        recheck = self.flow("verify", "example", "--task", "T01", "--", sys.executable, "-c", "exit(1)")
        self.assertNotEqual(recheck.returncode, 0)
        self.assertIn("待执行", self.ok("status", "example"))

    def test_changed_task_needs_new_confirmation(self):
        self.init("example", goal="目标")
        task = self.task("example", "T01")
        self.confirm("example", "T01")
        task.write_text(task.read_text().replace("仅修改支付重试逻辑", "允许修改所有模块"))
        self.assertIn("确认", self.flow("start", "example", "T01").stderr)

    def test_open_questions_block_only_affected_examples(self):
        mapping = self.init("payment")
        mapping.write_text(mapping.read_text() + "- [ ] Q01 [R02]: 返回哪些字段？\n")
        self.task("payment", "T01", example="E01")
        self.task("payment", "T02", example="E02")
        self.confirm("payment", "T01")
        result = self.flow("confirm", "payment", "T02", "--statement", "暂按旧行为处理")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Q01", result.stderr)
        mapping.write_text(mapping.read_text().replace("- [ ] Q01 [R02]: 返回哪些字段？",
                                                     "- [x] Q01 [R02]: 返回哪些字段？ 决定：响应使用首次结果。"))
        self.confirm("payment", "T02")

    def test_only_relevant_mapping_changes_expire_confirmation(self):
        mapping = self.init("payment")
        self.task("payment", "T01", example="E01")
        self.confirm("payment", "T01")
        mapping.write_text(mapping.read_text().replace("相同金额返回原结果", "相同金额返回原订单编号"))
        self.ok("start", "payment", "T01")
        mapping.write_text(mapping.read_text().replace("只产生一次扣款", "只允许一次扣款尝试"))
        result = self.flow("verify", "payment", "--", sys.executable, "-c", "assert True")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("确认", result.stderr)

    def test_legacy_requirement_can_keep_existing_task_format(self):
        self.init("legacy").unlink()
        index = self.repo / ".ai-workflow/legacy/tasks.md"
        index.write_text(index.read_text().replace("澄清与验收示例见 [Example Mapping](examples.md)。\n", ""))
        self.ok("add", "legacy", "T01", "--title", "旧任务")
        plan = self.repo / ".ai-workflow/legacy/tasks/T01.md"
        content = plan.read_text()
        for heading, body in SECTIONS.items():
            content = content.replace(f"## {heading}\n\n", f"## {heading}\n\n{body}\n")
        plan.write_text(content)
        self.confirm("legacy", "T01")
        self.ok("start", "legacy", "T01")

    def test_dependent_task_waits_for_reconfirmation_after_rule_change(self):
        mapping = self.init("payment")
        self.task("payment", "T01", example="E01")
        self.task("payment", "T02", after="T01", example="E02")
        self.confirm("payment", "T01")
        self.confirm("payment", "T02")
        self.ok("start", "payment", "T01")
        self.ok("verify", "payment", "--", sys.executable, "-c", "assert True")
        mapping.write_text(mapping.read_text().replace("只产生一次扣款", "只允许一次扣款尝试"))
        result = self.flow("start", "payment", "T02")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("T01", result.stderr)
        self.confirm("payment", "T01")
        self.ok("start", "payment", "T01")
        self.ok("verify", "payment", "--", sys.executable, "-c", "assert True")
        self.ok("start", "payment", "T02")

    def test_global_question_blocks_confirmation_until_decision_is_recorded(self):
        mapping = self.init("payment")
        self.task("payment", "T01")
        question = "本轮是否包含退款？"
        mapping.write_text(mapping.read_text() + f"- [ ] Q01 [*]: {question}\n")
        result = self.flow("confirm", "payment", "T01", "--statement", "确认支付重试")
        self.assertIn("Q01", result.stderr)
        mapping.write_text(mapping.read_text().replace("[ ] Q01", "[x] Q01"))
        result = self.flow("confirm", "payment", "T01", "--statement", "确认支付重试")
        self.assertIn("记录决定", result.stderr)
        mapping.write_text(mapping.read_text().replace(question, question + " 决定：仅含支付重试。"))
        self.confirm("payment", "T01")

    def test_audit_preserves_dirty_baseline_and_first_review_result(self):
        self.init("audit", audited=True)
        self.task("audit", "T01")
        self.task("audit", "T02", after="T01")
        self.confirm("audit", "T01")
        self.confirm("audit", "T02")
        self.ok("skill", "audit", "brainstorming", "--stage", "clarify", "--purpose", "澄清")
        self.ok("_observe-skill", "audit", "writing-plans", "--stage", "plan", "--source", "pi-read", "--evidence", "SKILL.md")
        (self.repo / "app.txt").write_text("pre-existing")
        (self.repo / "existing.txt").write_text("already here")
        baseline_index = self.git("ls-files", "--stage").stdout
        self.ok("start", "audit", "T01")
        self.ok("skill", "audit", "verification-before-completion", "--stage", "execute",
                "--task", "T01", "--purpose", "运行测试")
        (self.repo / "app.txt").write_text("implementation")
        (self.repo / "created.txt").write_text("new file")
        self.ok("verify", "audit", "--", sys.executable, "-c", "assert True")
        self.assertNotEqual(self.flow("start", "audit", "T02").returncode, 0)
        report = self.ok("audit", "audit", "T01")
        for token in ("brainstorming", "writing-plans", "verification-before-completion", "created.txt"):
            self.assertIn(token, report)
        self.assertNotIn("existing.txt", report)
        diff = self.ok("audit", "audit", "T01", "--diff")
        self.assertIn("-pre-existing", diff)
        self.assertNotIn("-before", diff)
        self.assertEqual(self.git("ls-files", "--stage").stdout, baseline_index)
        self.ok("review", "audit", "T01", "rework")
        self.ok("verify", "audit", "--", sys.executable, "-c", "assert True")
        self.ok("review", "audit", "T01", "accept")
        self.assertIn("0/1", self.ok("audit", "audit"))
        self.ok("start", "audit", "T02")

    def test_review_rejects_stale_worktree(self):
        self.init("audit", audited=True)
        self.task("audit", "T01")
        self.confirm("audit", "T01")
        self.ok("start", "audit", "T01")
        self.ok("verify", "audit", "--", sys.executable, "-c", "assert True")
        (self.repo / "app.txt").write_text("new changes after verification")
        self.assertNotEqual(self.flow("review", "audit", "T01", "accept").returncode, 0)
        self.ok("verify", "audit", "--", sys.executable, "-c", "assert True")
        self.ok("review", "audit", "T01", "accept")
        self.assertIn("1/1", self.ok("audit", "audit"))

    def test_audit_flags_normalized_file_changes_missing_from_git_patch(self):
        (self.repo / ".gitattributes").write_text("app.txt text eol=lf\n")
        (self.repo / "app.txt").write_bytes(b"before\n")
        self.init("audit", audited=True)
        self.task("audit", "T01")
        self.confirm("audit", "T01")
        self.ok("start", "audit", "T01")
        (self.repo / "app.txt").write_bytes(b"before\r\n")
        self.ok("verify", "audit", "--", sys.executable, "-c", "assert True")
        self.assertIn("无 Git 文本/二进制差异，请核对原文件：app.txt", self.ok("audit", "audit", "T01"))

    def test_review_rejects_modified_patch(self):
        self.init("audit", audited=True)
        self.task("audit", "T01")
        self.confirm("audit", "T01")
        self.ok("start", "audit", "T01")
        self.ok("verify", "audit", "--", sys.executable, "-c", "assert True")
        patch = next((self.repo / ".ai-workflow/audit/audit").glob("*.patch"))
        patch.write_text("altered")
        result = self.flow("review", "audit", "T01", "accept")
        self.assertIn("审阅差异已改变", result.stderr)
        result = self.flow("audit", "audit", "T01", "--diff")
        self.assertIn("审阅差异已改变", result.stderr)

    def test_missing_example_map_does_not_allow_confirmation(self):
        mapping = self.init("payment")
        self.task("payment", "T01")
        mapping.unlink()
        result = self.flow("confirm", "payment", "T01", "--statement", "确认")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("examples.md", result.stderr)

    def test_verify_command_cannot_change_source_and_pass(self):
        self.init("example", goal="目标")
        self.task("example", "T01")
        self.confirm("example", "T01")
        self.ok("start", "example", "T01")
        result = self.flow("verify", "example", "--", sys.executable, "-c", "open('app.txt','w').write('mutated')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("执行中", self.ok("status", "example"))


if __name__ == "__main__":
    unittest.main()
