"""Functional subagents retain independent model choices across legacy migrations."""
import copy
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agent_config
import ext
from role_catalog import ROLES, REVIEWERS, LEGACY_ROLES, semantic_settings
import roles
import setup_compact
import test_setup_agents


class SemanticRoleConfigTest(unittest.TestCase):
    def old_settings(self):
        return {'model': 'base', 'effort': 'medium', 'roles': {
            'reviewer-mid': {'model': 'hunter', 'effort': 'high'},
            'reviewer-lite': {'model': 'intent', 'effort': 'low'},
            'reviewer': {'model': 'deep-review', 'effort': 'max'},
            'compiler-lite': {'model': 'compiler', 'effort': 'high'},
        }, 'levels': {'fast': {'roles': {'reviewer-mid': {'effort': 'low'}}},
                      'deep': {'roles': {'reviewer': {'effort': 'high'}}}}}

    def resolve(self, settings, level='normal', client='codex'):
        cfg = {'executors': {client: settings}}
        return agent_config.resolve(ext.executor_config(cfg, client), level)

    def test_aliases_expand_by_layer_and_keep_all_levels(self):
        settings = self.old_settings()
        original = copy.deepcopy(settings)
        migrated = semantic_settings(settings)
        self.assertEqual(settings, original)
        self.assertEqual(semantic_settings(migrated), migrated)
        self.assertNotIn('compiler-lite', str(migrated))
        for level in ('fast', 'normal', 'deep'):
            before = self.resolve(settings, level)
            after = self.resolve(migrated, level)
            self.assertEqual(before['roles'], after['roles'])
            self.assertTrue(before['warnings'])
            self.assertFalse(after['warnings'])
            self.assertEqual(set(before['roles']), set(ROLES))
            self.assertFalse(set(before['roles']) & LEGACY_ROLES)
            self.assertEqual(after['roles']['context-compiler']['model'], 'compiler')
        normal = self.resolve(settings)['roles']
        deep = self.resolve(settings, 'deep')['roles']
        self.assertEqual(normal['intent-alignment']['model'], 'intent')
        self.assertEqual(normal['blind-hunter']['model'], 'hunter')
        self.assertTrue(all(deep[r]['model'] == 'deep-review' for r in REVIEWERS))
        self.assertTrue(all(deep[r]['effort'] == 'high' for r in REVIEWERS))

    def test_semantic_common_wins_over_alias_level_then_semantic_level_wins(self):
        settings = self.old_settings()
        settings['roles']['blind-hunter'] = {'model': 'blind-only', 'effort': 'medium'}
        settings['levels']['deep']['roles']['blind-hunter'] = {'effort': 'low'}
        for level in ('normal', 'deep'):
            out = self.resolve(settings, level)['roles']
            self.assertEqual(out['blind-hunter']['model'], 'blind-only')
            self.assertEqual(out['blind-hunter']['effort'], 'low' if level == 'deep' else 'medium')
            self.assertNotEqual(out['edge-case-hunter']['model'], 'blind-only')
            self.assertEqual(out, self.resolve(semantic_settings(settings), level)['roles'])

    def test_claude_default_layers_and_deep_arguments(self):
        for level in ('fast', 'normal', 'deep'):
            out, errors, warnings = roles.resolve({}, level)
            self.assertEqual((errors, warnings), ([], []))
            for role in REVIEWERS:
                expected = ('sonnet', 'high') if level == 'deep' else (
                    ('haiku', 'high') if role == 'intent-alignment' else ('sonnet', 'medium'))
                self.assertEqual((out[role]['model'], out[role]['effort']), expected)
            if level == 'deep':
                self.assertEqual(out['intent-alignment']['args'], {'model': 'sonnet'})
                self.assertEqual(out['blind-hunter']['args'], {'effort': 'high'})

    def test_claude_alias_migration_preserves_models_and_efforts(self):
        settings = {'roles': {
            'reviewer-mid': {'model': 'opus', 'effort': 'low'},
            'reviewer-lite': {'model': 'haiku', 'effort': 'medium'},
            'reviewer': {'model': 'sonnet', 'effort': 'max'},
            'compiler-lite': {'model': 'sonnet', 'effort': 'high'}},
            'levels': {'deep': {'roles': {'intent-alignment': {'model': 'haiku'}}}}}
        for level in ('fast', 'normal', 'deep'):
            self.assertEqual(self.resolve(settings, level, 'claude')['roles'],
                             self.resolve(semantic_settings(settings), level, 'claude')['roles'])

    def test_invalid_overridden_alias_value_fails_instead_of_disappearing(self):
        for value in ('', None, 'CONFIGURE_MODEL'):
            settings = {'roles': {'reviewer-mid': {'model': value},
                         **{r: {'model': 'explicit'} for r in REVIEWERS}}}
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.resolve(settings)

    def test_advanced_legacy_routes_compact_without_loss(self):
        old_roles = ('story-runner', 'implementer', 'reviewer', 'reviewer-mid',
                     'reviewer-lite', 'compiler-lite', 'triager', 'verifier')
        cfg = {'execution': {'backend': 'native'}, 'agents': {
            name: {'model': name + '-model', 'effort': 'high'} for name in old_roles},
            'roles': {name: {'agent': name} for name in old_roles},
            'routing': {'deep': {'reviewer': {'agent': 'reviewer-mid'}}}}
        compact = setup_compact.from_advanced(cfg)
        for level in ('fast', 'normal', 'deep'):
            old = agent_config.resolve(cfg, level)['roles']
            new = self.resolve(compact, level)['roles']
            for role in ROLES:
                self.assertEqual({k: v for k, v in old[role].items() if k != 'profile_id'},
                                 {k: v for k, v in new[role].items() if k != 'profile_id'})


class SemanticRoleSetupTest(unittest.TestCase):
    def setUp(self):
        fixture = test_setup_agents.AgentSetupTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.repo, self.config, self.cli = fixture.repo, fixture.config, fixture.cli

    def test_migration_never_overwrites_higher_layer_aliases(self):
        local = self.repo / '.auto-bmad.local.toml'
        for client, backend, lower, higher in (
                ('codex', 'native', 'project-model', 'local-model'),
                ('claude', 'legacy-plugin', 'sonnet', 'opus')):
            with self.subTest(client=client):
                self.config.write_text(f'[execution]\nbackend="{backend}"\n'
                    f'[executors.{client}.roles.reviewer-mid]\nmodel="{lower}"\neffort="medium"\n')
                local.write_text(f'[executors.{client}.roles.reviewer-mid]\nmodel="{higher}"\neffort="high"\n')
                before = self.config.read_bytes(), local.read_bytes()
                previous = {level: agent_config.read(str(self.repo), level)['roles']
                            for level in ('fast', 'normal', 'deep')}
                for extra in ((), ('--role', 'context-compiler', '--effort', 'medium')):
                    result = self.cli('agent', '--agent', client, '--layer', 'project',
                                      *extra, '--write', ok=False)
                    self.assertIn('migration would change', result['error'])
                    self.assertEqual(before, (self.config.read_bytes(), local.read_bytes()))
                # Migrate the higher layer first; the following project migration is safe.
                self.cli('agent', '--agent', client, '--layer', 'local', '--write')
                self.cli('agent', '--agent', client, '--layer', 'project', '--write')
                for level, expected in previous.items():
                    self.assertEqual(agent_config.read(str(self.repo), level)['roles'], expected)

    def test_setup_edits_each_agent_independently_and_migrates_only_own_client(self):
        original = ('[executors.codex.roles.reviewer-mid]\nmodel="hunters"\neffort="medium"\n'
                    '[executors.codex.roles.reviewer]\nmodel="deep"\n'
                    '[executors.codex.roles.compiler-lite]\nmodel="gpt-6-luna"\neffort="high"\n'
                    '[executors.claude.roles.reviewer-mid]\nmodel="opus"\n')
        self.config.write_text(original)
        previous = tomllib.loads(original)['executors']['claude']
        self.cli('agent', '--agent', 'codex', '--role', 'blind-hunter', '--model', 'blind', '--write')
        cfg = tomllib.loads(self.config.read_text())
        self.assertEqual(cfg['executors']['claude'], previous)
        self.assertFalse(set(cfg['executors']['codex'].get('roles', {})) & LEGACY_ROLES)
        for level in ('normal', 'deep'):
            selected = agent_config.read(str(self.repo), level)['roles']
            self.assertEqual(selected['blind-hunter']['model'], 'blind')
            self.assertEqual(selected['edge-case-hunter']['model'], 'deep' if level == 'deep' else 'hunters')
            self.assertEqual(selected['context-compiler']['model'], 'gpt-6-luna')
        self.cli('agent', '--agent', 'codex', '--role', 'edge-case-hunter', '--level', 'deep',
                 '--effort', 'low', '--write')
        selected = agent_config.read(str(self.repo), 'deep')['roles']
        self.assertEqual(selected['edge-case-hunter']['effort'], 'low')
        self.assertEqual(selected['blind-hunter']['model'], 'blind')
        saved = self.config.read_text()
        self.assertFalse(self.cli('agent', '--agent', 'codex', '--write')['written'])
        self.assertEqual(self.config.read_text(), saved)
