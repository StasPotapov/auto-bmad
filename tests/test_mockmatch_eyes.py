import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agent_config
import cli_verifier
import mockmatch_eyes as eyes
import verifier_tools


class EyesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.private = self.root / 'private'
        self.package = self.private / 'package'
        (self.package / 'bin').mkdir(parents=True)
        (self.package / 'agents').mkdir()
        self.prompt = self.package / 'agents/eyes.md'
        self.prompt.write_text('Shared eyes prompt; at most 8 images.')
        self.run = self.private / 'browser/build/mockmatch/fixture'
        self.run.mkdir(parents=True)
        (self.run / '400/diff').mkdir(parents=True)
        (self.run / '400/diff/r1.png').write_bytes(b'fixture')
        (self.run / 'report.json').write_text(json.dumps({'cells': [{'cell': '400', 'pixels': {'regions': [{'crop': 'r1.png', 'layout': 'design top, site bottom'}]}}]}))
        profile = agent_config.codex_roles({}, 'normal')['verifier']
        self.b = SimpleNamespace(root=self.root, private=self.private, story='1-1',
            manifest={'roles': {'verifier': profile}}, verifier_tool={'cli': str(self.package / 'bin/mockmatch')},
            stop=threading.Event(), verifier_done=threading.Event(), lease_fd=None,
            host_environment=lambda: dict(os.environ), environment=lambda names: {k: os.environ[k] for k in names if k in os.environ})
        self.host = {'configured': True, 'settings': {'eyes': {'enabled': True, 'model': 'gpt-6-luna', 'effort': 'low'}},
                     'prompt': str(self.prompt)}
        self.lines = 'run build/mockmatch/fixture  board: build/mockmatch/fixture/board.html\n'

    def test_tool_settings_own_model_and_effort_and_do_not_mutate_verifier(self):
        original = dict(self.b.manifest['roles']['verifier'])
        with patch.object(eyes, 'command', return_value=json.dumps(self.host)) as cmd:
            profile, prompt = eyes.settings(self.b)
            self.assertEqual((profile['model'], profile['effort'], profile['permissions']), ('gpt-6-luna', 'low', 'read-only'))
            self.assertEqual(self.b.manifest['roles']['verifier'], original)
            self.assertIn('Shared eyes', prompt)
            eyes.settings(self.b)
            self.assertEqual(cmd.call_count, 1)
        del self.b.verifier_tool['eyes_settings']
        self.host['settings']['eyes'].pop('effort')
        with patch.object(eyes, 'command', return_value=json.dumps(self.host)):
            self.assertNotIn('effort', eyes.settings(self.b)[0])

    def test_disabled_or_unconfigured_eyes_never_substitutes_verifier(self):
        for field in ('configured', 'enabled'):
            host = json.loads(json.dumps(self.host))
            if field == 'configured': host[field] = False
            else: host['settings']['eyes'][field] = False
            response = {'stdout': self.lines}
            with patch.object(eyes, 'command', return_value=json.dumps(host)), patch.object(eyes, 'execute') as execute:
                eyes.compare_verdict(self.b, response)
            execute.assert_not_called()
            self.assertIn('EYES_UNAVAILABLE', response['stdout'])
            self.assertTrue(self.b.verifier_tool['eyes_failures'])
            self.assertFalse(self.b.eyes_active)

    def test_run_and_prompt_cannot_escape_snapshot(self):
        self.assertEqual(eyes.run_path(self.b, self.lines), self.run)
        with self.assertRaises(ValueError):
            eyes.run_path(self.b, 'run ' + str(self.root) + '  board: x\n')
        self.host['prompt'] = str(self.run / 'report.json')
        with patch.object(eyes, 'command', return_value=json.dumps(self.host)), self.assertRaises(ValueError):
            eyes.settings(self.b)

    def test_independent_call_uses_shared_prompt_and_host_persists_notes(self):
        seen = {}
        def execute(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            self.assertTrue(self.b.eyes_active)
            self.assertFalse(kwargs['cancel'].is_set())
            self.b.verifier_done.set()
            self.assertTrue(kwargs['cancel'].is_set())
            self.b.verifier_done.clear()
            return {'execution_status': 'completed', 'result': {'status': 'done', 'report': 'PROBLEM r1 (800): missing button'}}
        detection = {'executable': '/fixture/codex', 'capabilities': {'read_only_enforcement': 'supported', 'image_input': 'supported'}}
        with patch.object(eyes, 'command', return_value=json.dumps(self.host)) as cmd, \
             patch.object(eyes.agent_adapters, 'detect', return_value=detection), patch.object(eyes, 'execute', side_effect=execute):
            response = {'stdout': self.lines}
            eyes.compare_verdict(self.b, response)
        self.assertIn('gpt-6-luna', seen['argv'])
        self.assertIn('model_reasoning_effort="low"', seen['argv'])
        self.assertIn('read-only', seen['argv'])
        self.assertIn('--image', seen['argv'])
        self.assertIn(str(self.run / '400/diff/r1.png'), seen['argv'])
        self.assertIn('Shared eyes prompt', seen['stdin'])
        self.assertIn('design top, site bottom', seen['stdin'])
        self.assertIn('PROBLEM r1', (self.run / 'notes.md').read_text())
        self.assertEqual(cmd.call_args.args[1], ['board', str(self.run)])
        self.assertIn('EYES: gpt-6-luna / low', response['stdout'])
        self.assertEqual(seen['metadata']['role'], 'mockmatch-eyes')

    def test_failed_or_malformed_role_cannot_write_notes(self):
        detection = {'executable': '/fixture/codex', 'capabilities': {'read_only_enforcement': 'supported', 'image_input': 'supported'}}
        for answer in ({'status': 'blocked', 'report': 'no image tool'}, {'status': 'done', 'report': 'looks good'}):
            with patch.object(eyes, 'command', return_value=json.dumps(self.host)), \
                 patch.object(eyes.agent_adapters, 'detect', return_value=detection), \
                 patch.object(eyes, 'execute', return_value={'execution_status': 'completed', 'result': answer}):
                response = {'stdout': self.lines}
                eyes.compare_verdict(self.b, response)
                self.assertIn('EYES_UNAVAILABLE', response['stdout'])
                self.assertFalse((self.run / 'notes.md').exists())

    def test_compare_with_differences_also_invokes_eyes(self):
        self.b.verifying = True
        self.b.session = {'writer': 'verifier'}
        self.b.session_path = self.private / 'session.json'
        self.b.verifier_tool['fields'] = {}
        def execute(argv, **kwargs):
            folder = kwargs['directory']; folder.mkdir()
            (folder / 'stdout.jsonl').write_text(self.lines)
            (folder / 'stderr.log').write_text('')
            return {'execution_status': 'completed', 'exit_code': 1}
        with patch.object(verifier_tools, 'execute', side_effect=execute), patch.object(eyes, 'compare_verdict') as evaluate:
            result = verifier_tools.run(self.b, ['compare', '--design', str(self.root / 'design.html')])
            self.assertEqual(result['code'], 1)
            evaluate.assert_called_once()

    def test_help_never_invokes_eyes(self):
        self.b.verifying = True
        self.b.session = {'writer': 'verifier'}
        self.b.session_path = self.private / 'session.json'
        def execute(argv, **kwargs):
            folder = kwargs['directory']; folder.mkdir()
            (folder / 'stdout.jsonl').write_text('compare help')
            (folder / 'stderr.log').write_text('')
            return {'execution_status': 'completed', 'exit_code': 0}
        with patch.object(verifier_tools, 'execute', side_effect=execute), patch.object(eyes, 'compare_verdict') as evaluate:
            for flag in ('--help', '-h'):
                verifier_tools.run(self.b, ['compare', flag])
            evaluate.assert_not_called()

    def test_attachment_budget_and_path_checks(self):
        cell = {'cell': '400', 'pixels': {'regions': [{'crop': 'r1.png', 'layout': 'design top, site bottom'}] * 10}}
        (self.run / 'report.json').write_text(json.dumps({'cells': [cell]}))
        images, total, labels = eyes.image_inputs(self.run)
        self.assertEqual((len(images), total), (8, 10))
        (self.run / '400/diff/r1.png').unlink()
        (self.run / '400/diff/r1.png').symlink_to(self.prompt)
        with self.assertRaises(ValueError): eyes.image_inputs(self.run)

    def test_unavailable_eyes_cannot_be_reported_as_pass(self):
        b = self.b
        b.id = 'fixture'; b.state = self.root; b.verifier_tool['fields'] = {}
        b.serve_verifier_tools = lambda: None
        b.handoff = lambda request: {'execution_status': 'completed', 'attempt': 'fixture',
                                     'result': {'status': 'done', 'report': 'VERDICT: pass'}}
        b.verifier_tool['eyes_failures'] = ['no image tool']
        item = {'name': 'mockmatch', 'instructions': str(cli_verifier.ROOT / 'extensions/mockmatch/verify.md'), 'fields': {}}
        with patch.object(verifier_tools, 'prepare', return_value=self.root / 'bridge'), \
             patch.object(cli_verifier, 'revision', return_value='base'):
            result = cli_verifier._run(b, item, {'stories': [{'title': 'Fixture'}]}, {'report': 'Fixture'}, 'base', 1, [])
        self.assertEqual(result['verdict'], 'skipped')
        self.assertIn('no image tool', result['reason'])

if __name__ == '__main__':
    unittest.main()
