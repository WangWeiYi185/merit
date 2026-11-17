import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import task_graphify as graphify
from graphify_helpers import install_graphify, plan


class GraphifyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requirement = self.root / '.ai-workflow' / 'demo'
        self.requirement.mkdir(parents=True)
        (self.root / 'a.py').write_text('def a():\n    return 1\n')
        (self.root / 'b.py').write_text('def b():\n    return 2\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        install_graphify(self.bin)
        env = patch.dict(os.environ, {'PATH': str(self.bin) + os.pathsep + os.environ['PATH']})
        env.start()
        self.addCleanup(env.stop)

    def build(self, text=None, **kwargs):
        return graphify.prepare(self.root, self.requirement, 'T01', text or plan(), **kwargs)

    def artifact(self, record, key):
        return self.requirement / record[key]

    def test_rebuild_does_not_retain_removed_input(self):
        (self.root / 'c.py').write_text('pass\n')
        first = self.build(plan(inputs='- GRAPHIFY_INPUT b.py\n- GRAPHIFY_INPUT c.py'))
        old_graph = self.artifact(first, 'graph').read_bytes()
        old_manifest = self.artifact(first, 'manifest').read_bytes()
        second = self.build()
        self.assertNotEqual(first['manifest'], second['manifest'])
        graph = json.loads(self.artifact(second, 'graph').read_text())
        self.assertEqual({node['file'] for node in graph['nodes']}, {'a.py', 'b.py'})
        self.assertEqual(self.artifact(first, 'graph').read_bytes(), old_graph)
        self.assertEqual(self.artifact(first, 'manifest').read_bytes(), old_manifest)

    def test_failed_build_preserves_previous_record(self):
        first = self.build()
        original = self.artifact(first, 'manifest').read_bytes()
        for flag in ('GRAPHIFY_TEST_FAIL', 'GRAPHIFY_TEST_MISSING'):
            with self.subTest(flag=flag), patch.dict(os.environ, {flag: '1'}):
                with self.assertRaises(graphify.ScopeError):
                    self.build()
            self.assertEqual(self.artifact(first, 'manifest').read_bytes(), original)
            graphify.validate_current(self.root, self.requirement, first, plan())

    def test_scope_rejects_noncanonical_and_secret_paths(self):
        for name in ('/a.py', '../a.py', './a.py', 'x/../a.py', 'x//a.py',
                     '*.py', '.git/a.py', 'vendor/a.py', '.env', 'private.pem'):
            with self.subTest(name=name), self.assertRaises(graphify.ScopeError):
                graphify.parse_scope(plan(editable='- MODIFY ' + name))

    def test_parent_symlink_is_rejected(self):
        (self.root / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(graphify.ScopeError):
            self.build(plan(editable='- MODIFY link/a.py'))

    def test_read_only_evidence_is_not_mirrored(self):
        (self.root / 'rules.md').write_text('business rule')
        record = self.build(plan(evidence='- READ_ONLY_EVIDENCE rules.md'))
        self.assertIn('rules.md', record['sources'])
        data = json.loads(self.artifact(record, 'graph').read_text())
        self.assertEqual({n['file'] for n in data['nodes']}, {'a.py', 'b.py'})
        (self.root / 'rules.md').write_text('changed')
        with self.assertRaises(graphify.ScopeError):
            graphify.validate_current(self.root, self.requirement, record,
                                      plan(evidence='- READ_ONLY_EVIDENCE rules.md'))

    def test_editable_source_needs_no_extra_graphify_input(self):
        record = self.build(plan(inputs=''))
        self.assertEqual(record['inputs'], ['a.py'])

    def test_no_analyzable_source_is_an_error(self):
        (self.root / 'config.txt').write_text('value')
        with self.assertRaises(graphify.ScopeError):
            self.build(plan(editable='- MODIFY config.txt', inputs=''))

    def test_before_includes_deleted_source(self):
        record = self.build(plan(editable='- DELETE a.py', inputs='- GRAPHIFY_INPUT b.py'))
        self.assertEqual(record['inputs'], ['a.py', 'b.py'])
        self.assertEqual(record['phase'], 'before')

    def test_graph_tampering_and_create_race_are_rejected(self):
        text = plan(editable='- MODIFY a.py\n- CREATE new.py')
        record = self.build(text)
        (self.root / 'new.py').write_text('pass')
        with self.assertRaises(graphify.ScopeError):
            graphify.validate_current(self.root, self.requirement, record, text)
        (self.root / 'new.py').unlink()
        self.artifact(record, 'graph').write_text('{"nodes": []}')
        with self.assertRaises(graphify.ScopeError):
            graphify.validate_current(self.root, self.requirement, record, text)

    def test_after_includes_created_and_omits_deleted_source(self):
        text = plan(editable='- DELETE a.py\n- CREATE new.py', inputs='- GRAPHIFY_INPUT b.py')
        (self.root / 'a.py').unlink()
        (self.root / 'new.py').write_text('def new():\n    return 3\n')
        record = self.build(text, phase='after')
        self.assertEqual(record['inputs'], ['new.py', 'b.py'])
        self.assertIsNone(record['sources']['a.py'])
        self.assertEqual(record['phase'], 'after')

    def test_relation_delta_ignores_unstable_ids(self):
        a = {'nodes': [{'id': '1', 'file': 'a.py', 'label': 'a'},
                       {'id': '2', 'file': 'b.py', 'label': 'b'}],
             'edges': [{'source': '1', 'target': '2', 'relation': 'calls'},
                       {'source': '1', 'target': '2', 'relation': 'imports'}]}
        b = {'nodes': [{'id': 'new-b', 'file': 'b.py', 'label': 'b'},
                       {'id': 'new-a', 'file': 'a.py', 'label': 'a'}],
             'links': [{'source': 'new-a', 'target': 'new-b', 'relation': 'imports'},
                       {'source': 'new-a', 'target': 'new-b', 'relation': 'calls'}]}
        first, second = self.root / 'first.json', self.root / 'second.json'
        first.write_text(json.dumps(a)); second.write_text(json.dumps(b))
        left, limits = graphify.graph_relations(first)
        right, limits2 = graphify.graph_relations(second)
        self.assertEqual(left, right)
        self.assertEqual(sum(left.values()), 2)
        self.assertFalse(limits or limits2)

    def test_artifact_paths_cannot_escape_task_or_phase(self):
        record = self.build()
        for name in ('../outside', '/tmp/outside', record['manifest'].replace('/before/', '/after/')):
            with self.subTest(name=name), self.assertRaises(graphify.ScopeError):
                graphify.validate_artifacts(self.requirement, {**record, 'manifest': name})
        external = self.root / 'external.json'
        external.write_text('{}')
        self.artifact(record, 'graph').unlink()
        self.artifact(record, 'graph').symlink_to(external)
        with self.assertRaises(graphify.ScopeError):
            graphify.validate_artifacts(self.requirement, record)

    def test_empty_or_invalid_graph_cannot_be_registered(self):
        for flag in ('GRAPHIFY_TEST_EMPTY', 'GRAPHIFY_TEST_INVALID'):
            with self.subTest(flag=flag), patch.dict(os.environ, {flag: '1'}):
                with self.assertRaises(graphify.ScopeError):
                    self.build()

    def test_input_change_during_extraction_is_rejected(self):
        with patch.dict(os.environ, {'GRAPHIFY_TEST_MUTATE': str(self.root / 'a.py')}):
            with self.assertRaises(graphify.ScopeError):
                self.build()

    def test_symlinked_build_parent_cannot_write_outside_scope(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.requirement / 'graphify-scope').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(graphify.ScopeError):
            self.build()
        self.assertEqual(list(outside.iterdir()), [])

    def test_relative_source_directory_is_not_stripped_from_identity(self):
        path = self.root / 'identity.json'
        path.write_text(json.dumps({'nodes': [
            {'id': 'a', 'file': 'lib/source/a.py', 'label': 'a'},
            {'id': 'b', 'file': 'lib/source/b.py', 'label': 'b'}],
            'edges': [{'source': 'a', 'target': 'b', 'relation': 'calls'}]}))
        edges, limits = graphify.graph_relations(path)
        self.assertEqual(next(iter(edges))[0][0], 'lib/source/a.py')
        self.assertFalse(limits)

    def test_artifacts_must_share_the_same_build(self):
        first, second = self.build(), self.build()
        with self.assertRaises(graphify.ScopeError):
            graphify.artifact_path(self.requirement, {**first, 'graph': second['graph']}, 'graph')

    def test_legacy_manifest_without_phase_or_version_is_readable(self):
        import hashlib
        scope = {'editable': {'a.py': 'MODIFY'}, 'graphify_input': ['b.py'], 'read_only_evidence': []}
        base = self.requirement / 'graphify-scope/T01'
        base.mkdir(parents=True)
        graph = base / 'graph.json'
        graph.write_text('{"nodes": [], "links": []}')
        digest = lambda data: hashlib.sha256(data).hexdigest()
        record = {'task': 'T01', 'scope': scope,
                  'sources': {name: digest((self.root / name).read_bytes()) for name in ('a.py', 'b.py')},
                  'scope_sha256': digest(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()),
                  'graph': 'graphify-scope/T01/graph.json', 'graph_sha256': digest(graph.read_bytes()),
                  'graphify_exit_code': 0, 'inputs': ['a.py', 'b.py']}
        manifest = base / 'manifest.json'
        manifest.write_text(json.dumps(record))
        record.update(manifest='graphify-scope/T01/manifest.json', manifest_sha256=digest(manifest.read_bytes()))
        graphify.validate_current(self.root, self.requirement, record, plan())
        (self.root / 'a.py').write_text('changed')
        with self.assertRaises(graphify.ScopeError):
            graphify.validate_current(self.root, self.requirement, record, plan())

    def test_scope_error_is_concise(self):
        import subprocess
        import sys
        from test_workflow import CLI
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        def flow(*args):
            return subprocess.run([sys.executable, '-B', str(CLI), *args], cwd=self.root,
                                  capture_output=True, text=True)
        self.assertEqual(flow('init', 'bad', '--goal', 'bad scope').returncode, 0)
        self.assertEqual(flow('add', 'bad', 'T01', '--title', 'bad', '--investigation',
                              '--graphify-context').returncode, 0)
        path = self.root / '.ai-workflow/bad/tasks/T01.md'
        path.write_text(path.read_text().replace('## 修改范围\n\n', '## 修改范围\n\n- MODIFY ../a.py\n'))
        result = flow('graphify', 'bad', 'T01')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('路径', result.stderr)
