import json
from pathlib import Path
import tempfile
import unittest

import task_audit


class AuditEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'audit'

    def event(self, **overrides):
        args = dict(kind='input', name='rules', stage='execute', task='T01',
                    summary='目录约束', source='pi-read', node='run-1',
                    detail={'text': 'keep every implementation'})
        args.update(overrides)
        return task_audit.store_event(self.directory, **args)

    def test_original_input_survives_later_changes_and_default_event_is_compact(self):
        detail = {'text': 'old rule', 'path': 'AGENTS.md', 'offset': 3, 'limit': 8}
        event = self.event(detail=detail)
        detail['text'] = 'new rule'
        self.assertEqual(task_audit.load_evidence(self.directory, event['evidence'])['text'], 'old rule')
        self.assertNotIn('detail', event)
        self.assertEqual(task_audit.events(self.directory)[0]['id'], event['id'])

    def test_secret_fields_and_sensitive_file_contents_are_not_retained(self):
        event = self.event(detail={'api_key': 'synthetic-secret', 'text': 'Authorization: Bearer fake-secret\npassword=demo-password'})
        saved = task_audit.load_evidence(self.directory, event['evidence'])
        raw = json.dumps(saved)
        self.assertNotIn('synthetic-secret', raw)
        self.assertNotIn('fake-secret', raw)
        self.assertNotIn('demo-password', raw)
        self.assertIn('REDACTED', raw)
        event = self.event(detail={'path': '/tmp/.env', 'content': 'not safe to retain'})
        self.assertNotIn('not safe to retain', json.dumps(task_audit.load_evidence(self.directory, event['evidence'])))

    def test_evidence_tampering_escape_and_symlink_are_rejected(self):
        event = self.event()
        path = self.directory / 'evidence' / (event['evidence'] + '.json')
        original = path.read_bytes()
        path.write_text('{"text":"altered"}')
        with self.assertRaises(task_audit.AuditError):
            task_audit.load_evidence(self.directory, event['evidence'])
        path.write_bytes(original)
        with self.assertRaises(task_audit.AuditError):
            task_audit.load_evidence(self.directory, '../outside')
        outside = Path(self.temp.name) / 'outside.json'
        outside.write_bytes(original)
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(task_audit.AuditError):
            task_audit.load_evidence(self.directory, event['evidence'])

    def test_legacy_skill_log_symlink_cannot_read_or_overwrite_outside_audit(self):
        self.directory.mkdir()
        outside = Path(self.temp.name) / 'outside.jsonl'
        outside.write_text('{"name":"outside"}\n')
        (self.directory / 'skills.jsonl').symlink_to(outside)
        with self.assertRaises(task_audit.AuditError):
            task_audit.skills(self.directory)
        with self.assertRaises(task_audit.AuditError):
            task_audit.record_skill(self.directory, name='new')
        self.assertEqual(outside.read_text(), '{"name":"outside"}\n')

    def test_same_content_is_retained_once_but_executions_are_distinct(self):
        first, second = self.event(), self.event()
        self.assertEqual(first['evidence'], second['evidence'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(list((self.directory / 'evidence').glob('*.json'))), 1)
        self.assertEqual(len(task_audit.events(self.directory)), 2)

    def test_invalid_event_shape_is_rejected_before_it_corrupts_the_board(self):
        with self.assertRaises(task_audit.AuditError):
            self.event(kind={'not': 'a node kind'})
        self.directory.mkdir(exist_ok=True)
        (self.directory / 'events.jsonl').write_text('{"kind":"tool"}\n')
        with self.assertRaises(task_audit.AuditError):
            task_audit.events(self.directory)

    def test_terminal_controls_are_not_replayed_in_summaries(self):
        event = self.event(summary='unsafe\x1b]52;clipboard\x07')
        self.assertNotIn('\x1b', event['summary'])
        self.assertNotIn('\x07', event['summary'])


if __name__ == '__main__':
    unittest.main()
