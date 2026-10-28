"""Tests for roles.py, the role overrides in write_profile.py and `setup.py role`.
python3 -m unittest discover tests"""
import os
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import roles  # noqa: E402
import setup  # noqa: E402
import write_profile as wp  # noqa: E402


class ResolveTest(unittest.TestCase):
    def test_empty_config_keeps_the_agent_type_defaults(self):
        out, errors, warnings = roles.resolve({})
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(set(out), set(roles.ROLES))
        self.assertEqual(out["implementer"]["default"], {"model": "opus[1m]", "effort": "medium"})
        self.assertEqual(out["reviewer-lite"]["model"], "haiku")
        self.assertTrue(all(r["args"] == {} for r in out.values()))

    def test_every_role_has_a_frontmatter_model_and_effort(self):
        for role in roles.ROLES:
            d = roles.frontmatter(role)
            self.assertTrue(d["model"] and d["effort"], role)

    def test_override_goes_to_args_and_a_default_value_does_not(self):
        out, errors, _ = roles.resolve({"roles": {
            "implementer": {"model": "sonnet", "effort": "high"},
            "reviewer-mid": {"model": "sonnet", "effort": "medium"}}})
        self.assertEqual(errors, [])
        self.assertEqual(out["implementer"]["args"], {"model": "sonnet", "effort": "high"})
        self.assertEqual(out["reviewer-mid"]["args"], {})

    def test_bad_values_and_other_providers_are_errors(self):
        _, errors, _ = roles.resolve({"roles": {
            "implementer": {"model": "k3.1-pro", "provider": "kimi"},
            "verifier": {"effort": "huge"}}})
        self.assertEqual(len(errors), 3)
        self.assertTrue(any("provider" in e for e in errors))

    def test_unknown_role_and_key_are_warnings(self):
        out, errors, warnings = roles.resolve({"roles": {"orchestrator": {"model": "opus"},
                                                         "implementer": {"temperature": 1}}})
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)
        self.assertEqual(out["implementer"]["args"], {})

    def test_default_clears_a_lower_layer_override(self):
        out, errors, _ = roles.resolve({"roles": {"implementer": {"model": "opus[1m]", "effort": "default"},
                                                  "verifier": {"model": "default"}}})
        self.assertEqual(errors, [])
        self.assertEqual((out["implementer"]["args"], out["verifier"]["args"]), ({}, {}))
        self.assertEqual(out["implementer"]["model"], "opus[1m]")

    def test_unreadable_config_gives_defaults_and_a_warning(self):
        with tempfile.TemporaryDirectory() as repo, \
                mock.patch.dict(os.environ, {"AUTO_BMAD_CONFIG": os.path.join(repo, "none.toml")}):
            with open(os.path.join(repo, ".auto-bmad.toml"), "w", encoding="utf-8") as fh:
                fh.write('hook = "x"\n[roles.implementer]\nmodel = "sonnet"\n')
            out, errors, warnings = roles.load_roles(repo)
        self.assertEqual(errors, [])
        self.assertEqual(out["implementer"]["args"], {})
        self.assertTrue(any("role overrides are not applied" in w for w in warnings))

    def test_opus_over_a_1m_default_warns(self):
        _, _, warnings = roles.resolve({"roles": {"implementer": {"model": "opus"},
                                                  "verifier": {"model": "opus"}}})
        self.assertEqual(len(warnings), 1)
        self.assertIn("1M", warnings[0])
        self.assertIn('"opus[1m]"', warnings[0])

    def test_opus_1m_keeps_the_default_or_is_an_error(self):
        out, errors, _ = roles.resolve({"roles": {"story-runner": {"model": "opus[1m]"},
                                                  "reviewer": {"model": "opus[1m]"}}})
        self.assertEqual(out["story-runner"]["args"], {})
        self.assertEqual(out["story-runner"]["model"], "opus[1m]")
        self.assertEqual(len(errors), 1)
        self.assertIn("[roles.reviewer].model", errors[0])


class ProfileArgsTest(unittest.TestCase):
    def test_empty_overrides_leave_the_profile_unchanged(self):
        for level in wp.DISABLED:
            self.assertEqual(wp.build(level, {}), wp.build(level))
            self.assertNotIn("Agent parameters", wp.build(level))

    def test_overrides_follow_their_agent_type(self):
        args = {"implementer": {"model": "sonnet", "effort": "high"},
                "reviewer-mid": {"effort": "high"}, "compiler-lite": {"model": "sonnet"}}
        facts = tomllib.loads(wp.build("normal", args))["workflow"]["persistent_facts"]
        e = next(f for f in facts if f.startswith("Model policy"))
        g = next(f for f in facts if f.startswith("Context-compilation policy"))
        self.assertIn('`subagent_type: "auto-bmad:bmad-implementer"` with Agent parameters '
                      '`model: "sonnet"`, `effort: "high"`', e)
        self.assertIn('`"auto-bmad:bmad-reviewer-mid"` with Agent parameters `effort: "high"`', e)
        self.assertNotIn('bmad-reviewer-lite"` with', e)
        self.assertIn(wp.ARGS_RULE, e)
        self.assertIn('`subagent_type: "auto-bmad:bmad-compiler-lite"` with Agent parameters '
                      '`model: "sonnet"`', g)

    def test_override_of_a_role_the_level_does_not_use_adds_nothing(self):
        text = wp.build("normal", {"reviewer": {"effort": "max"}})
        self.assertEqual(text, wp.build("normal"))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, "_bmad", "custom"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.env = mock.patch.dict(os.environ, {"AUTO_BMAD_CONFIG": os.path.join(self.repo, "user.toml")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def config(self, text):
        with open(os.path.join(self.repo, ".auto-bmad.toml"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def profile(self):
        with mock.patch.object(sys, "argv", ["write_profile.py", "--level", "normal", "--repo", self.repo]):
            return wp.main()

    def test_profile_refuses_a_broken_roles_config(self):
        self.config('[roles.implementer]\nprovider = "kimi"\n')
        self.assertEqual(self.profile(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "_bmad", "custom", "bmad-build-auto.user.toml")))

    def test_profile_writes_the_overrides(self):
        self.config('[roles.implementer]\neffort = "high"\n')
        self.assertEqual(self.profile(), 0)
        with open(os.path.join(self.repo, "_bmad", "custom", "bmad-build-auto.user.toml"), encoding="utf-8") as fh:
            self.assertIn('bmad-implementer"` with Agent parameters `effort: "high"`', fh.read())

    def role(self, **kw):
        a = types.SimpleNamespace(role="implementer", model=None, effort=None, layer="project", write=True)
        a.__dict__.update(kw)
        return setup.cmd_role(a, self.repo)

    def test_setup_role_replaces_only_its_table(self):
        self.config('[run]\nlevel = "deep"\n\n[roles.implementer]\nmodel = "opus"\n\n'
                    '[roles.verifier]\neffort = "high"\n')
        out, code = self.role(model="sonnet", effort="high")
        self.assertEqual(code, 0)
        cfg = tomllib.loads(out["content"])
        self.assertEqual(cfg["run"], {"level": "deep"})
        self.assertEqual(cfg["roles"], {"implementer": {"model": "sonnet", "effort": "high"},
                                        "verifier": {"effort": "high"}})
        out, _ = self.role()
        self.assertNotIn("implementer", tomllib.loads(out["content"])["roles"])

    def test_setup_role_handles_a_commented_header(self):
        self.config('[roles.implementer]  # mine\nmodel = "opus"\n\n[[hook]]\nname = "h"\n')
        out, code = self.role(effort="high")
        self.assertEqual(code, 0, out)
        cfg = tomllib.loads(out["content"])
        self.assertEqual(cfg["roles"], {"implementer": {"effort": "high"}})
        self.assertEqual(cfg["hook"], [{"name": "h"}])

    def test_setup_role_refuses_forms_it_cannot_edit(self):
        for text in ('[roles]\nimplementer.model = "opus"\n',
                     'roles = {implementer = {model = "opus"}}\n',
                     '[[hook]]\nname = "h"\ncommand = """\n[roles.implementer]\n"""\n'):
            self.config(text)
            out, code = self.role(model="sonnet")
            self.assertEqual(code, 1, text)
            with open(os.path.join(self.repo, ".auto-bmad.toml"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text)

    def test_setup_role_checks_values_and_writes_the_user_layer(self):
        self.assertEqual(self.role(role="orchestrator", model="opus")[1], 1)
        self.assertEqual(self.role(model="k3")[1], 1)
        self.assertEqual(self.role(role="reviewer", model="opus[1m]")[1], 1)
        self.assertEqual(self.role(model="opus[1m]", write=False)[1], 0)
        out, code = self.role(layer="user", effort="low")
        self.assertEqual(code, 0)
        self.assertEqual(out["path"], os.path.join(self.repo, "user.toml"))
        self.assertTrue(os.path.exists(out["path"]))


if __name__ == "__main__":
    unittest.main()
