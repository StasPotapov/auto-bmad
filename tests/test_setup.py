"""Unit tests for setup.py: stages, Android detection, init and headless files.
python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import setup  # noqa: E402


def write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


APP_GRADLE = 'plugins { id("com.android.application") }\nandroid { defaultConfig { applicationId = "com.example.%s" } }\n'


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        os.environ["AUTO_BMAD_CONFIG"] = os.path.join(self.repo, "absent.toml")

    def tearDown(self):
        del os.environ["AUTO_BMAD_CONFIG"]
        self.tmp.cleanup()

    def args(self, **kw):
        base = dict(level="normal", parallel="conservative", width=3, no_android=False,
                    android_module=None, no_web=False, test_command=None, write=False, force=False)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_check_points_to_bmad_first(self):
        st, _ = setup.cmd_check(self.repo)
        self.assertFalse(st["bmad"]["installed"])
        self.assertEqual(st["next"]["stage"], "bmad")

    def test_old_bmad_needs_update(self):
        write(self.repo, setup.MANIFEST, "installation:\n  version: 6.2.2\n")
        st, _ = setup.cmd_check(self.repo)
        self.assertFalse(st["bmad"]["version_ok"])
        self.assertIn("update", st["bmad"])

    def test_android_prefers_app_module_and_lists_candidates(self):
        write(self.repo, "probe/build.gradle.kts", APP_GRADLE % "probe")
        write(self.repo, "composeApp/build.gradle.kts", APP_GRADLE % "main")
        write(self.repo, "composeApp/src/androidMain/kotlin/A.kt", "window.addFlags(FLAG_SECURE)")
        app = setup.android_app(self.repo)
        self.assertEqual(app["module"], "composeApp")
        self.assertEqual(app["package"], "com.example.main")
        self.assertTrue(app["flag_secure"])
        self.assertEqual(app["candidates"], ["composeApp", "probe"])
        self.assertEqual(setup.android_app(self.repo, "probe")["package"], "com.example.probe")

    def test_init_writes_once_and_ext_reads_it(self):
        write(self.repo, "pyproject.toml", "[project]\nname='x'\n")
        out, code = setup.cmd_init(self.args(level="deep", write=True), self.repo)
        self.assertEqual((code, out["written"]), (0, True))
        import plan_run
        self.assertEqual(plan_run.run_defaults(self.repo)["level"], "deep")
        out, code = setup.cmd_init(self.args(write=True), self.repo)
        self.assertEqual((code, out.get("exists")), (2, True))

    def test_web_app_from_package_json(self):
        write(self.repo, "web/package.json",
              '{"scripts": {"dev": "vite"}, "dependencies": {"react": "18"}, "devDependencies": {"vite": "5"}}')
        write(self.repo, "web/pnpm-lock.yaml")
        web = setup.web_app(self.repo)
        self.assertEqual((web["framework"], web["serve"], web["url"]),
                         ("vite", "cd web && pnpm run dev", "http://localhost:5173"))

    def test_static_site_and_no_web(self):
        self.assertIsNone(setup.web_app(self.repo))
        write(self.repo, "index.html", "<h1>x</h1>")
        self.assertEqual(setup.web_app(self.repo)["url"], "http://localhost:8000")

    def test_init_writes_mockmatch_block_or_disables_it(self):
        write(self.repo, "package.json", '{"scripts": {"dev": "next dev"}, "dependencies": {"next": "15"}}')
        out, _ = setup.cmd_init(self.args(), self.repo)
        self.assertIn('name = "mockmatch"\nserve = "npm run dev"\nurl = "http://localhost:3000"', out["content"])
        out, _ = setup.cmd_init(self.args(no_web=True), self.repo)
        self.assertIn('name = "mockmatch"\nenabled = false', out["content"])
        st, _ = setup.cmd_check(self.repo)
        self.assertEqual(st["project"]["web"]["framework"], "next")
        self.assertIn("mockmatch", st["extras"])

    def test_headless_allows_mockmatch_for_web(self):
        write(self.repo, "package.json", '{"scripts": {"dev": "vite"}, "devDependencies": {"vite": "5"}}')
        perms = setup.headless_settings(self.repo)["permissions"]["allow"]
        for item in ("Bash(mockmatch:*)", "Bash(npm:*)", "Bash(curl:*)"):
            self.assertIn(item, perms)

    def test_headless_has_no_push(self):
        out, code = setup.cmd_headless(self.args(write=True), self.repo)
        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, setup.HEADLESS)) as fh:
            perms = json.load(fh)["permissions"]
        self.assertIn("Bash(auto-bmad:*)", perms["allow"])
        self.assertIn("Bash(git push:*)", perms["deny"])


if __name__ == "__main__":
    unittest.main()
