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

    def graph_task(self, requirement='graph', task='T01', *, mode='--graphify-context', after=None, legacy=False):
        from graphify_helpers import install_graphify
        if not (self.repo / '.ai-workflow' / requirement).exists():
            self.init(requirement, audited=True)
        bin_dir = self.repo / '.ai-workflow' / 'bin'
        bin_dir.mkdir(exist_ok=True)
        install_graphify(bin_dir)
        from unittest.mock import patch
        env = patch.dict(os.environ, {'PATH': str(bin_dir) + os.pathsep + os.environ['PATH']})
        env.start()
        self.addCleanup(env.stop)
        (self.repo / 'app.py').write_text('def main():\n    return 1\n')
        (self.repo / 'rules.md').write_text('keep behavior')
        self.ok('add', requirement, task, '--title', '代码改动', '--example', 'E01', mode,
                *('--after', after) if after else ())
        path = self.repo / '.ai-workflow' / requirement / 'tasks' / f'{task}.md'
        content = path.read_text()
        fields = {**SECTIONS, '修改范围': '- MODIFY app.py',
                  'Graphify 与只读证据范围': '- READ_ONLY_EVIDENCE rules.md',
                  'Graphify 依赖证据': 'EXTRACTED app.py:1，已核对源码',
                  '流程变化与确定编码上下文': 'main 返回 1 → 2，保持无副作用，E01'}
        for heading, body in fields.items():
            content = content.replace(f'## {heading}\n\n', f'## {heading}\n\n{body}\n')
        if legacy:
            content = content.replace('"version": 2', '"version": 1')
        path.write_text(content)
        return path

    def test_before_binds_only_task_inputs(self):
        path = self.graph_task()
        self.ok('graphify', 'graph', 'T01')
        self.confirm('graph', 'T01')
        (self.repo / 'unrelated.txt').write_text('unrelated')
        self.ok('start', 'graph', 'T01')
        self.ok('block', 'graph', '--kind', 'external', '--issue', 'pause', '--impact', 'test', '--next', 'resume')
        self.ok('resolve', 'graph', 'T01', '--detail', 'resume')
        for name in ('app.py', 'rules.md'):
            original = (self.repo / name).read_text()
            (self.repo / name).write_text(original + '\nchanged\n')
            self.assertNotEqual(self.flow('start', 'graph', 'T01').returncode, 0)
            (self.repo / name).write_text(original)
        self.ok('start', 'graph', 'T01')

    def test_legacy_graphify_context_remains_readable(self):
        self.graph_task(legacy=True)
        self.ok('graphify', 'graph', 'T01')
        self.confirm('graph', 'T01')
        self.ok('start', 'graph', 'T01')
        (self.repo / 'app.py').write_text('def main():\n    return 2\n')
        self.ok('verify', 'graph', '--', sys.executable, '-c', 'assert True')
        self.ok('review', 'graph', 'T01', 'accept')

    def test_completed_dependency_does_not_require_before_source(self):
        self.graph_task(legacy=True)
        self.task('graph', 'T02', after='T01')
        self.confirm('graph', 'T02')
        self.ok('graphify', 'graph', 'T01')
        self.confirm('graph', 'T01')
        self.ok('start', 'graph', 'T01')
        (self.repo / 'app.py').write_text('def main():\n    return 2\n')
        self.ok('verify', 'graph', '--', sys.executable, '-c', 'assert True')
        self.ok('review', 'graph', 'T01', 'accept')
        self.ok('start', 'graph', 'T02')

    def test_unflagged_task_never_runs_graphify(self):
        self.init('plain', audited=True)
        self.task('plain', 'T01')
        self.confirm('plain', 'T01')
        self.ok('start', 'plain', 'T01')
        self.ok('verify', 'plain', '--', sys.executable, '-c', 'assert True')
        self.ok('review', 'plain', 'T01', 'accept')
        self.assertFalse((self.repo / '.ai-workflow/plain/graphify-scope').exists())

    def graph_record(self, phase='after'):
        import json
        path = self.repo / '.ai-workflow/graph/tasks/T01.md'
        records = [json.loads(line[2:]) for line in path.read_text().splitlines()
                   if line.startswith('- {"kind": ')]
        return next(r for r in reversed(records)
                    if r['kind'] == 'graphify_context' and r.get('phase', 'before') == phase)

    def prepare_delivery(self, *, audit_only=False):
        self.graph_task(mode='--graphify-audit' if audit_only else '--graphify-context')
        if not audit_only:
            self.ok('graphify', 'graph', 'T01')
        self.confirm('graph', 'T01')
        self.ok('start', 'graph', 'T01')
        (self.repo / 'app.py').write_text('def main():\n    return 2\n')
        self.ok('verify', 'graph', '--', sys.executable, '-c', 'assert True')

    def complete_graph_report(self):
        record = self.graph_record()
        path = self.repo / '.ai-workflow/graph' / record['report']
        text = path.read_text()
        for heading, body in {
            '实际流程': 'main() 返回 2，入口和出口均无外部调用。',
            '条件、异常与副作用': '无分支和副作用；保留原异常传播方式。',
            '保留行为': '函数签名及无副作用保持不变。',
            '规则、示例与验证': 'R01 / E01；本任务验证日志确认成功。',
            '源码核验': 'EXTRACTED app.py:1-2，已逐行核对 return 2。',
            '未解析边界': '本例无动态依赖；图不证明完整业务语义。',
        }.items():
            text = text.replace(f'## {heading}\n\n待核验', f'## {heading}\n\n{body}')
        path.write_text(text)

    def seal_delivery(self):
        self.ok('graphify', 'graph', 'T01', '--phase', 'after')
        self.complete_graph_report()
        self.ok('graphify', 'graph', 'T01', '--phase', 'after', '--seal')

    def test_audit_only_confirms_without_graph(self):
        self.prepare_delivery(audit_only=True)
        self.assertFalse((self.repo / '.ai-workflow/graph/graphify-scope/T01/before').exists())
        self.assertNotEqual(self.flow('review', 'graph', 'T01', 'accept').returncode, 0)
        self.seal_delivery()
        record = self.graph_record()
        report = (self.repo / '.ai-workflow/graph' / record['report']).read_text()
        self.assertIn('无前置图', report)
        self.ok('review', 'graph', 'T01', 'accept')

    def test_before_is_immutable_after_delivery(self):
        self.prepare_delivery()
        before = self.graph_record('before')
        original = (self.repo / '.ai-workflow/graph' / before['manifest']).read_bytes()
        self.seal_delivery()
        self.assertEqual((self.repo / '.ai-workflow/graph' / before['manifest']).read_bytes(), original)
        self.assertNotEqual(before['graph'], self.graph_record()['graph'])
        self.ok('review', 'graph', 'T01', 'accept')

    def test_report_requires_source_verified_flow(self):
        self.prepare_delivery()
        self.ok('graphify', 'graph', 'T01', '--phase', 'after')
        result = self.flow('graphify', 'graph', 'T01', '--phase', 'after', '--seal')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('核验', result.stderr)
        self.complete_graph_report()
        self.ok('graphify', 'graph', 'T01', '--phase', 'after', '--seal')
        self.ok('review', 'graph', 'T01', 'accept')

    def test_after_requires_successful_current_verification(self):
        self.graph_task()
        self.assertNotEqual(self.flow('graphify', 'graph', 'T01', '--phase', 'after').returncode, 0)
        self.ok('graphify', 'graph', 'T01')
        self.confirm('graph', 'T01')
        self.ok('start', 'graph', 'T01')
        self.flow('verify', 'graph', '--', sys.executable, '-c', 'exit(1)')
        self.assertNotEqual(self.flow('graphify', 'graph', 'T01', '--phase', 'after').returncode, 0)
        self.ok('verify', 'graph', '--', sys.executable, '-c', 'assert True')
        self.assertFalse((self.repo / '.ai-workflow/graph/graphify-scope/T01/after').exists())
        (self.repo / 'app.py').write_text('changed after verify')
        self.assertNotEqual(self.flow('graphify', 'graph', 'T01', '--phase', 'after').returncode, 0)

    def test_callflow_export_failure_blocks_acceptance(self):
        from unittest.mock import patch
        self.prepare_delivery()
        with patch.dict(os.environ, {'GRAPHIFY_TEST_EXPORT_FAIL': '1'}):
            self.assertNotEqual(self.flow('graphify', 'graph', 'T01', '--phase', 'after').returncode, 0)
        self.assertNotEqual(self.flow('review', 'graph', 'T01', 'accept').returncode, 0)

    def test_review_rejects_stale_or_tampered_audit(self):
        self.prepare_delivery()
        self.seal_delivery()
        record = self.graph_record()
        for key in ('graph', 'callflow', 'report'):
            path = self.repo / '.ai-workflow/graph' / record[key]
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            self.assertNotEqual(self.flow('review', 'graph', 'T01', 'accept').returncode, 0)
            path.write_bytes(original)
        (self.repo / 'rules.md').write_text('changed ignored evidence')
        self.assertNotEqual(self.flow('review', 'graph', 'T01', 'accept').returncode, 0)
        (self.repo / 'rules.md').write_text('keep behavior')
        self.ok('verify', 'graph', '--', sys.executable, '-c', 'assert True')
        self.assertNotEqual(self.flow('review', 'graph', 'T01', 'accept').returncode, 0)
        self.seal_delivery()
        self.ok('review', 'graph', 'T01', 'accept')

    def test_reverification_does_not_bypass_after_gate(self):
        self.prepare_delivery()
        self.seal_delivery()
        self.ok('review', 'graph', 'T01', 'accept')
        self.ok('verify', 'graph', '--task', 'T01', '--', sys.executable, '-c', 'assert True')
        self.assertIn('待审阅', self.ok('status', 'graph'))
        self.assertNotEqual(self.flow('review', 'graph', 'T01', 'accept').returncode, 0)
        self.seal_delivery()
        self.ok('review', 'graph', 'T01', 'accept')

    def test_v2_accepted_dependency_can_start(self):
        self.prepare_delivery()
        self.task('graph', 'T02', after='T01')
        self.confirm('graph', 'T02')
        self.seal_delivery()
        self.ok('review', 'graph', 'T01', 'accept')
        self.ok('start', 'graph', 'T02')

    def test_graphify_scope_blocks_outside_edits(self):
        self.prepare_delivery()
        (self.repo / 'outside.py').write_text('pass')
        self.assertNotEqual(self.flow('verify', 'graph', '--', sys.executable, '-c', 'assert True').returncode, 0)
        self.assertIn('阻塞', self.ok('status', 'graph'))
        self.assertNotEqual(self.flow('graphify', 'graph', 'T01', '--phase', 'after').returncode, 0)

    def test_ignored_read_only_evidence_cannot_change_during_implementation(self):
        self.graph_task(mode='--graphify-audit')
        (self.repo / '.gitignore').write_text('rules.md\n')
        self.confirm('graph', 'T01')
        self.ok('start', 'graph', 'T01')
        (self.repo / 'rules.md').write_text('new business rule')
        result = self.flow('verify', 'graph', '--', sys.executable, '-c', 'assert True')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('只读', result.stderr)

    def test_pure_create_audit_needs_no_existing_code_input(self):
        path = self.graph_task(mode='--graphify-audit')
        path.write_text(path.read_text().replace('- MODIFY app.py', '- CREATE new.py'))
        self.confirm('graph', 'T01')
        self.ok('start', 'graph', 'T01')
        (self.repo / 'new.py').write_text('def value():\n    return 2\n')
        self.ok('verify', 'graph', '--', sys.executable, '-c', 'assert True')
        self.ok('graphify', 'graph', 'T01', '--phase', 'after')
        self.assertEqual(self.graph_record()['inputs'], ['new.py'])

    def test_status_only_loads_current_task_graph_context(self):
        self.graph_task()
        self.graph_task(task='T02', after='T01')
        self.ok('graphify', 'graph', 'T01')
        self.ok('graphify', 'graph', 'T02')
        status = self.ok('status', 'graph')
        self.assertIn('Graphify：T01', status)
        self.assertNotIn('Graphify：T02', status)

    def record_rules(self, path, body):
        text = path.read_text()
        if '## 适用规范\n' not in text:
            text = text.replace('\n## 工作流记录\n', '\n## 适用规范\n\n\n## 工作流记录\n')
        path.write_text(text.replace('## 适用规范\n\n', f'## 适用规范\n\n{body}\n'))

    def test_task_template_includes_applicable_rules(self):
        from workflow import sections
        self.init('rules')
        path = self.task('rules', 'T01')
        self.assertIn('适用规范', sections(path.read_text()))

    def test_rule_references_are_audited_after_handoff(self):
        self.init('rules', audited=True)
        path = self.task('rules', 'T01')
        body = ('- AIWorkflow:skills/swift-api-design-guidelines/SKILL.md — execute/verify；参数标签。\n'
                '- 项目:AGENTS.md — execute/verify；沿用当前模块，不迁移旧目录。')
        self.record_rules(path, body)
        self.confirm('rules', 'T01')
        self.ok('start', 'rules', 'T01')
        self.ok('verify', 'rules', '--', sys.executable, '-c', 'assert True')
        report = self.ok('audit', 'rules', 'T01')
        self.assertIn(body, report)
        self.assertIn(body, path.read_text())
        self.ok('review', 'rules', 'T01', 'accept')

    def test_changing_rule_selection_expires_confirmation(self):
        self.init('rules')
        path = self.task('rules', 'T01')
        self.record_rules(path, '- AIWorkflow:skills/swift-api-design-guidelines/SKILL.md — Swift API。')
        self.confirm('rules', 'T01')
        path.write_text(path.read_text().replace('Swift API。', 'Swift API；项目例外需要调整。'))
        result = self.flow('start', 'rules', 'T01')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('确认', result.stderr)

    def test_external_coding_rules_are_not_graphify_inputs(self):
        import json
        path = self.graph_task(mode='--graphify-audit')
        self.record_rules(path, f'- AIWorkflow:docs/structure/ios.md — 实际资源位于 {CLI.parent / "docs/structure/ios.md"}，用于文件归属。')
        self.confirm('graph', 'T01')
        records = [json.loads(line[2:]) for line in path.read_text().splitlines()
                   if line.startswith('- {"kind": ')]
        confirmation = next(r for r in reversed(records) if r['kind'] == 'confirmation')
        self.assertEqual(set(confirmation['sources']), {'app.py', 'rules.md'})
        self.assertEqual(confirmation['scope']['graphify_input'], [])
        self.ok('start', 'graph', 'T01')

    def test_old_task_without_rule_section_still_completes(self):
        self.init('legacy-rules', audited=True)
        path = self.task('legacy-rules', 'T01')
        path.write_text(path.read_text().replace('## 适用规范\n\n\n', ''))
        self.confirm('legacy-rules', 'T01')
        self.ok('start', 'legacy-rules', 'T01')
        self.ok('verify', 'legacy-rules', '--', sys.executable, '-c', 'assert True')
        self.ok('review', 'legacy-rules', 'T01', 'accept')

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
