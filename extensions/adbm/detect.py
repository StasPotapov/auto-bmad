#!/usr/bin/env python3
"""Does the adbm check apply: the story diff touches the Android app UI.

stdin — {"files": [...]} from `verify.py plan`; the command runs from the project root.
Exit 0 — yes: res/ resources, AndroidManifest.xml, Kotlin/Java with @Composable,
Activity, Fragment or View. Otherwise 1.
"""
import json
import os
import re
import sys

UI_CODE = re.compile(r"@Composable|:\s*(?:\w+\.)*(?:Component|AppCompat|Fragment)?Activity\(|"
                     r":\s*(?:\w+\.)*Fragment\(|extends\s+\w*(?:Activity|Fragment)\b|:\s*\w*View\(")


def applies(path):
    norm = path.replace("\\", "/")
    if norm.endswith("AndroidManifest.xml") or re.search(r"(^|/)src/\w+/res/", norm):
        return True
    if not norm.endswith((".kt", ".java")):
        return False
    try:
        with open(norm, encoding="utf-8", errors="ignore") as fh:
            return bool(UI_CODE.search(fh.read()))
    except OSError:
        return False


def main():
    data = json.load(sys.stdin)
    if not any(os.path.exists(f) for f in ("settings.gradle", "settings.gradle.kts")):
        return 1
    return 0 if any(applies(f) for f in data.get("files", [])) else 1


if __name__ == "__main__":
    sys.exit(main())
