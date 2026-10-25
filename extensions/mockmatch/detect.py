#!/usr/bin/env python3
"""Does the mockmatch check apply: the story diff touches the web UI.

stdin — {"files": [...]} from `verify.py plan`; the command runs from the project root.
Exit 0 — yes: markup and styles (.html, .css, .scss, .vue, .svelte, .astro, .jsx, .tsx…),
JS/TS in UI folders (components, pages, app, routes, views, layouts) of a project with
package.json, a Tailwind config, files in public/ or static/. Tests do not count. Otherwise 1.
"""
import json
import os
import re
import sys

UI_EXT = (".html", ".htm", ".css", ".scss", ".sass", ".less", ".styl", ".pcss",
          ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".mdx")
SCRIPT_EXT = (".js", ".ts", ".mjs", ".cjs")
UI_DIRS = re.compile(r"(^|/)(components|pages|app|routes|views|layouts|ui)/")
TESTS = re.compile(r"(^|/)(__tests__|tests?|e2e|cypress|playwright)/|\.(test|spec|stories)\.\w+$")
SKIP = re.compile(r"(^|/)(node_modules|dist|build|\.next|\.svelte-kit|\.astro|_bmad|_bmad-output|\.claude)/")


def applies(path, web):
    norm = path.replace("\\", "/")
    if SKIP.search(norm) or TESTS.search(norm):
        return False
    if norm.endswith(UI_EXT):
        return True
    if not web:
        return False
    if re.search(r"(^|/)tailwind\.config\.\w+$", norm) or re.search(r"(^|/)(public|static)/", norm):
        return True
    return norm.endswith(SCRIPT_EXT) and bool(UI_DIRS.search(norm))


def main():
    data = json.load(sys.stdin)
    web = os.path.exists("package.json")
    return 0 if any(applies(f, web) for f in data.get("files", [])) else 1


if __name__ == "__main__":
    sys.exit(main())
