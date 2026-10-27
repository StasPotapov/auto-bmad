#!/usr/bin/env python3
"""Does the mockmatch check apply: the story diff touches the web UI.

stdin — {"files": [...]} from `verify.py plan`; the command runs from the project root.
Exit 0 — yes: markup and styles (.html, .css, .scss, .vue, .svelte, .astro, .jsx, .tsx…);
for a file under a package.json (in its folder or above, up to the project root, so a
frontend/ subfolder counts too) also JS/TS in UI folders (components, pages, app, routes,
views, layouts, ui, lib), a Tailwind or PostCSS config, files in public/ or static/.
Tests and the design/ snapshot do not count. Otherwise 1.
"""
import json
import os
import re
import sys

UI_EXT = (".html", ".htm", ".css", ".scss", ".sass", ".less", ".styl", ".pcss",
          ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".mdx")
SCRIPT_EXT = (".js", ".ts", ".mjs", ".cjs")
UI_DIRS = re.compile(r"(^|/)(components|pages|app|routes|views|layouts|ui|lib)/")
TESTS = re.compile(r"(^|/)(__tests__|tests?|e2e|cypress|playwright)/|\.(test|spec|stories)\.\w+$")
SKIP = re.compile(r"(^|/)(node_modules|dist|build|\.next|\.svelte-kit|\.astro|_bmad|_bmad-output|\.claude)/"
                  r"|^design/")


def web_package(path):
    """The folder of the nearest package.json at or above the file, up to the root; None if none."""
    parts = path.split("/")[:-1]
    for i in range(len(parts), -1, -1):
        folder = "/".join(parts[:i])
        if os.path.exists(os.path.join(folder or ".", "package.json")):
            return folder
    return None


def applies(path):
    norm = path.replace("\\", "/")
    if SKIP.search(norm) or TESTS.search(norm):
        return False
    if norm.endswith(UI_EXT):
        return True
    pkg = web_package(norm)
    if pkg is None:
        return False
    rel = norm[len(pkg) + 1:] if pkg else norm
    if re.search(r"(^|/)(tailwind|postcss)\.config\.\w+$", rel) or re.search(r"(^|/)(public|static)/", rel):
        return True
    return rel.endswith(SCRIPT_EXT) and bool(UI_DIRS.search(rel))


def main():
    data = json.load(sys.stdin)
    return 0 if any(applies(f) for f in data.get("files", [])) else 1


if __name__ == "__main__":
    sys.exit(main())
