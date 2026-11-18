import json
from pathlib import Path
import sys
import unittest

import test_workflow


class OrchestrationTest(unittest.TestCase):
    setUp = test_workflow.WorkflowTest.setUp
    git = test_workflow.WorkflowTest.git
    flow = test_workflow.WorkflowTest.flow
    ok = test_workflow.WorkflowTest.ok
    init = test_workflow.WorkflowTest.init
    task = test_workflow.WorkflowTest.task
    confirm = test_workflow.WorkflowTest.confirm

    def parent(self):
        self.init('parent', audited=True)
        self.task('parent', 'T01')

    def derive(self, name='child', task='T01'):
        result = self.flow('derive', 'parent', task, name, '--goal', '原样聚类组件',
                           '--reason', '从只读审计派生目录调整交付，需要独立规划验收',
                           '--scope', '仅两套弹窗组件', '--deliverable', '原样目录与有效工程引用',
                           '--acceptance', '内容一致、构建及调用方回归', '--statement', '用户批准该独立范围')
        if result.returncode == 0:
            (self.repo / '.ai-workflow' / name / 'examples.md').write_text(
                '# 子需求独立澄清\n\n## 规则\n- R01: 保留实现。\n\n## 示例\n'
                '- E01 [R01]: 移动后内容不变。\n\n## 未决问题\n')
        return result

    def finish(self, requirement, task):
        self.confirm(requirement, task)
        self.ok('start', requirement, task)
        self.ok('verify', requirement, '--', sys.executable, '-c', 'assert True')
        return self.ok('review', requirement, task, 'accept')

    def events(self, requirement):
        path = self.repo / '.ai-workflow' / requirement / 'audit/events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_derive_creates_real_parent_pointer_and_visible_origin(self):
        self.parent()
        result = self.derive()
        self.assertEqual(result.returncode, 0, result.stderr)
        child = self.repo / '.ai-workflow/child'
        self.assertEqual(json.loads((child / 'superiors').read_text()), [
            {'requirement': 'parent', 'task': 'T01', 'entry': 'parent/tasks/T01.md'}
        ])
        board = json.loads(self.ok('board', 'parent', '--json'))
        self.assertEqual(board['tasks'][0]['children'][0]['requirement'], 'child')
        events = self.events('child')
        derived = next(event for event in events if event['kind'] == 'derivation')
        self.assertIn('只读审计', derived['summary'])
        self.assertTrue(derived['evidence'])

    def test_bad_parent_does_not_leave_orphan_and_explicit_contract_is_required(self):
        self.parent()
        result = self.derive(task='T99')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.ai-workflow/child').exists())
        result = self.flow('derive', 'parent', 'T01', 'child', '--goal', 'new goal')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.ai-workflow/child').exists())
        index = self.repo / '.ai-workflow/parent/tasks.md'
        original = index.read_text()
        row = next(line for line in original.splitlines() if line.startswith('| [T01]'))
        index.write_text(original + row + '\n')
        self.assertNotEqual(self.derive().returncode, 0)
        self.assertFalse((self.repo / '.ai-workflow/child').exists())

    def test_link_existing_child_is_idempotent_and_rejects_cycle(self):
        self.parent()
        self.init('child', audited=True)
        self.task('child', 'T01')
        args = ('link', 'child', 'parent', 'T01', '--reason', '补充此前遗漏的来源', '--statement', '用户确认关联')
        self.ok(*args)
        self.ok(*args)
        pointers = json.loads((self.repo / '.ai-workflow/child/superiors').read_text())
        self.assertEqual(len(pointers), 1)
        result = self.flow('link', 'parent', 'child', 'T01', '--reason', 'bad cycle', '--statement', 'test')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.ai-workflow/parent/superiors').exists())

    def test_verify_or_partial_acceptance_does_not_recall_requirement(self):
        self.parent()
        self.assertEqual(self.derive().returncode, 0)
        self.task('child', 'T01')
        self.task('child', 'T02')
        self.confirm('child', 'T01')
        self.ok('start', 'child', 'T01')
        self.ok('verify', 'child', '--', sys.executable, '-c', 'assert True')
        self.assertFalse(any(e['kind'] == 'recall' for e in self.events('child')))
        self.ok('review', 'child', 'T01', 'accept')
        self.assertFalse(any(e['kind'] == 'recall' for e in self.events('child')))
        output = self.finish('child', 'T02')
        self.assertIn('parent/T01', output)
        self.assertEqual(len([e for e in self.events('child') if e['kind'] == 'recall']), 1)
        self.ok('review', 'child', 'T02', 'accept')
        self.assertEqual(len([e for e in self.events('child') if e['kind'] == 'recall']), 1)
        self.assertIn('待执行', self.ok('status', 'parent'))

    def test_missing_parent_entry_does_not_undo_child_acceptance(self):
        self.parent()
        self.assertEqual(self.derive().returncode, 0)
        self.task('child', 'T01')
        self.init('another-parent', audited=True)
        self.task('another-parent', 'T01')
        self.ok('link', 'child', 'another-parent', 'T01', '--reason', '两个真实上层入口', '--statement', '用户确认')
        (self.repo / '.ai-workflow/parent/tasks/T01.md').unlink()
        output = self.finish('child', 'T01')
        self.assertIn('不可用', output)
        self.assertIn('another-parent/T01', output)
        self.assertIn('通过', self.ok('status', 'child'))
        self.assertIn('待执行', self.ok('status', 'another-parent'))

    def test_board_hides_internal_details_but_each_event_can_be_deep_audited(self):
        self.parent()
        detail = json.dumps({'text': 'INTERNAL_TRACE_' * 300, 'offset': 10, 'limit': 20})
        self.ok('trace', 'parent', '--task', 'T01', '--stage', 'plan', '--kind', 'input',
                '--name', 'source context', '--summary', '只读第10到29行', '--detail', detail)
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        node = next(n for n in board['nodes'] if n['name'] == 'source context')
        self.assertEqual(node['source'], 'declared')
        self.assertNotIn('INTERNAL_TRACE_', self.ok('board', 'parent', 'T01'))
        original = json.loads(self.ok('evidence', 'parent', node['evidence'], '--json'))
        self.assertEqual(original['offset'], 10)
        self.assertEqual(original['text'], 'INTERNAL_TRACE_' * 300)

    def test_corrupt_unrelated_pointer_is_not_shown_as_a_fake_child(self):
        self.parent()
        self.ok('init', 'unrelated', '--goal', 'Unrelated goal')
        (self.repo / '.ai-workflow/unrelated/superiors').write_text('broken pointer')
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        self.assertNotIn('unrelated', [child['requirement'] for child in board['tasks'][0]['children']])
        self.assertTrue(any('unrelated' in warning for warning in board['warnings']))

    def test_link_does_not_install_an_unrecorded_relation_when_evidence_fails(self):
        self.parent()
        self.ok('init', 'child', '--goal', 'Child')
        child = self.repo / '.ai-workflow/child'
        audit = child / 'audit'
        audit.mkdir(exist_ok=True)
        outside = self.repo / 'outside-record.jsonl'
        outside.write_text('unchanged')
        (audit / 'events.jsonl').symlink_to(outside)
        result = self.flow('link', 'child', 'parent', 'T01', '--reason', '独立交付', '--statement', '用户已确认')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((child / 'superiors').exists())
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_draft_inputs_can_be_deep_audited_without_faking_historical_snapshot(self):
        self.parent()
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        item = next(item for item in board['inputs'] if item['name'] == '最大范围')
        self.assertTrue(item['evidence'])
        original = json.loads(self.ok('evidence', 'parent', item['evidence'], '--json'))
        self.assertIn('仅修改支付重试逻辑', original['task_brief'])
        self.assertIn('非执行时', original['limitation'])
        path = self.repo / '.ai-workflow/parent/tasks/T01.md'
        path.write_text(path.read_text().replace('仅修改支付重试逻辑', '修改全部源码'))
        self.assertNotEqual(self.flow('evidence', 'parent', item['evidence'], '--json').returncode, 0)

    def test_observed_rules_and_skills_remain_distinct_from_declared_capabilities(self):
        self.parent()
        payload = json.dumps({'kind': 'rule', 'name': 'AGENTS.md', 'stage': 'plan', 'task': 'T01',
                              'source': 'pi-event', 'summary': '实际上下文规则', 'detail': {'text': 'old rule'}})
        self.ok('_observe-event', 'parent', '--payload', payload)
        self.ok('skill', 'parent', 'writing-plans', '--stage', 'plan', '--purpose', '拆分任务')
        data = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        self.assertTrue(any(r['name'] == 'AGENTS.md' and r['source'] == 'pi-event' for r in data['rules']))
        self.assertTrue(any(s['name'] == 'writing-plans' and s['source'] == 'declared' for s in data['skills']))
        self.assertNotIn('独立审查Agent', json.dumps(data, ensure_ascii=False))

    def test_verification_deep_view_uses_captured_output_not_mutable_log(self):
        self.parent()
        self.confirm('parent', 'T01')
        self.ok('start', 'parent', 'T01')
        self.ok('verify', 'parent', '--', sys.executable, '-c', "print('ORIGINAL_OUTPUT')")
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        item = next(item for item in board['outputs'] if item['name'] == 'verification')
        path = self.repo / '.ai-workflow/parent/tasks/T01.md'
        records = [json.loads(line[2:]) for line in path.read_text().splitlines() if line.startswith('- {"kind": ')]
        log = next(record['log'] for record in records if record['kind'] == 'verification')
        (self.repo / '.ai-workflow/parent' / log).write_text('MUTATED_LOG')
        data = self.ok('evidence', 'parent', item['evidence'], '--json')
        self.assertIn('ORIGINAL_OUTPUT', data)
        self.assertNotIn('MUTATED_LOG', data)

    def test_binary_verification_output_is_retained_without_breaking_success(self):
        self.parent()
        self.confirm('parent', 'T01')
        self.ok('start', 'parent', 'T01')
        self.ok('verify', 'parent', '--', sys.executable, '-c', 'import sys; sys.stdout.buffer.write(bytes([255]))')
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        item = next(item for item in board['outputs'] if item['name'] == 'verification')
        data = json.loads(self.ok('evidence', 'parent', item['evidence'], '--json'))
        self.assertIn('replacement', data['output_encoding'])

    def test_named_build_failure_is_not_overwritten_by_static_success(self):
        self.parent()
        self.confirm('parent', 'T01')
        self.ok('start', 'parent', 'T01')
        failed = self.flow('verify', 'parent', '--check', 'build', '--', sys.executable, '-c', 'exit(1)')
        self.assertNotEqual(failed.returncode, 0)
        static = self.flow('verify', 'parent', '--check', 'static', '--', sys.executable, '-c', 'assert True')
        self.assertNotEqual(static.returncode, 0)
        self.assertNotEqual(self.flow('review', 'parent', 'T01', 'accept').returncode, 0)
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        self.assertEqual(board['checks']['build']['result'], 'failed')
        self.assertEqual(board['checks']['static']['result'], 'passed')
        self.ok('verify', 'parent', '--check', 'build', '--', sys.executable, '-c', 'assert True')
        self.ok('review', 'parent', 'T01', 'accept')

    def test_named_checks_from_an_old_workspace_do_not_count_as_current_acceptance(self):
        self.parent()
        self.confirm('parent', 'T01')
        self.ok('start', 'parent', 'T01')
        self.ok('verify', 'parent', '--check', 'static', '--', sys.executable, '-c', 'assert True')
        (self.repo / 'app.txt').write_text('new implementation after static check')
        result = self.flow('verify', 'parent', '--check', 'build', '--', sys.executable, '-c', 'assert True')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(self.flow('review', 'parent', 'T01', 'accept').returncode, 0)
        board = json.loads(self.ok('board', 'parent', 'T01', '--json'))
        self.assertFalse(board['checks']['static']['current'])
        self.ok('verify', 'parent', '--check', 'static', '--', sys.executable, '-c', 'assert True')
        self.ok('review', 'parent', 'T01', 'accept')

    def test_changed_previously_accepted_child_plan_does_not_recall_whole_requirement(self):
        self.parent()
        self.assertEqual(self.derive().returncode, 0)
        first = self.task('child', 'T01')
        self.task('child', 'T02')
        self.finish('child', 'T01')
        first.write_text(first.read_text().replace('仅修改支付重试逻辑', '允许修改全部源码'))
        self.finish('child', 'T02')
        self.assertFalse(any(e['kind'] == 'recall' for e in self.events('child')))

    def test_board_does_not_unfold_tool_internals_and_rejects_symlink_task(self):
        self.parent()
        self.ok('_observe-event', 'parent', '--payload', json.dumps({
            'kind': 'tool', 'name': 'bash', 'stage': 'execute', 'task': 'T01',
            'source': 'pi-event', 'summary': 'INTERNAL_OPERATION_SHOULD_BE_FOLDED', 'detail': {'output': 'full output'}}))
        self.assertNotIn('INTERNAL_OPERATION_SHOULD_BE_FOLDED', self.ok('board', 'parent', 'T01'))
        entry = self.repo / '.ai-workflow/parent/tasks/T01.md'
        outside = self.repo / 'outside.md'
        outside.write_text(entry.read_text())
        entry.unlink()
        entry.symlink_to(outside)
        result = self.flow('board', 'parent', 'T01', '--json')
        self.assertNotEqual(result.returncode, 0)

    def test_superiors_path_escape_and_symlink_are_rejected(self):
        self.parent()
        outside = self.repo / 'outside.md'
        outside.write_text('outside')
        parent_entry = self.repo / '.ai-workflow/parent/tasks/T01.md'
        parent_entry.unlink()
        parent_entry.symlink_to(outside)
        result = self.derive()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.ai-workflow/child').exists())


if __name__ == '__main__':
    unittest.main()
