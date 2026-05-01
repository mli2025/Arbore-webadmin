#!/usr/bin/env python3
"""Sync the project version metadata in one place.

设计意图（中文）:
- 每次发版必须保证三处版本号一致：
  1. backend/main.py 中的 API_VERSION (运行时返回)
  2. version.json (OTA 客户端拉取的清单)
  3. frontend/src/App.vue 中默认 apiVersion + changelog 数组
- 同时 BUILD_TIME 总是要刷为当前 UTC 时间。
- 这个脚本以 backend/main.py 的 API_VERSION 为权威源，自动把版本号 / 构建时间
  写到 version.json，并刷新 main.py 中的 BUILD_TIME。
- changelog 文案仍由人工维护（语义化的描述需要人写），脚本只校验是否更新。

Design (English):
- Single source of truth: ``API_VERSION`` in ``backend/main.py``.
- Run with no args to:
    * stamp BUILD_TIME = current UTC ISO-8601
    * sync version.json::version & build_time
    * verify that frontend changelog references the current version
- Pass --check to fail (non-zero exit) when versions diverge: handy for CI
  pre-commit hooks.

Usage:
    python update-build-time.py            # write timestamps & sync
    python update-build-time.py --check    # only validate, don't write
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN_PY = os.path.join(ROOT, 'backend', 'main.py')
VERSION_JSON = os.path.join(ROOT, 'version.json')
APP_VUE = os.path.join(ROOT, 'frontend', 'src', 'App.vue')


def read(p: str) -> str:
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


def write(p: str, content: str) -> None:
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)


def extract_main_version() -> str:
    m = re.search(r'API_VERSION\s*=\s*"([^"]+)"', read(MAIN_PY))
    if not m:
        raise RuntimeError(f'API_VERSION not found in {MAIN_PY}')
    return m.group(1)


def stamp_main_build_time(ts: str) -> bool:
    content = read(MAIN_PY)
    new_content = re.sub(r'BUILD_TIME\s*=\s*"[^"]*"',
                         f'BUILD_TIME = "{ts}"', content)
    if new_content != content:
        write(MAIN_PY, new_content)
        return True
    return False


def sync_version_json(version: str, ts: str) -> bool:
    if not os.path.exists(VERSION_JSON):
        raise RuntimeError(f'{VERSION_JSON} missing')
    with open(VERSION_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    changed = False
    if data.get('version') != version:
        data['version'] = version
        changed = True
    if data.get('build_time') != ts:
        data['build_time'] = ts
        changed = True
    if changed:
        with open(VERSION_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write('\n')
    return changed


def assert_app_vue_has_version(version: str) -> str | None:
    """Return None when the frontend already references the version, else
    return a warning string.

    We intentionally don't auto-edit App.vue: changelog entries are written
    by humans and we just want a visible reminder when somebody forgot to
    add a new entry.
    """
    text = read(APP_VUE)
    needle1 = f"v{version}"           # changelog version literal
    needle2 = f"apiVersion = ref('v{version}')"
    missing = []
    if needle1 not in text:
        missing.append(f'{needle1} (no changelog entry)')
    if needle2 not in text:
        missing.append(f"apiVersion default not 'v{version}'")
    if missing:
        return ('frontend/src/App.vue out of sync: '
                + ' / '.join(missing))
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true',
                        help='only validate, do not write any file')
    args = parser.parse_args(argv)

    version = extract_main_version()
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'API_VERSION={version}')

    warn = assert_app_vue_has_version(version)
    if warn:
        print(f'! {warn}')
        if args.check:
            return 2

    if args.check:
        # Validation mode: ensure version.json already matches
        with open(VERSION_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('version') != version:
            print(f'! version.json says {data.get("version")!r}, '
                  f'expected {version!r}')
            return 3
        print('OK: version.json matches main.py and frontend')
        return 0

    if stamp_main_build_time(ts):
        print(f'+ BUILD_TIME -> {ts}')
    else:
        print(f'  BUILD_TIME already {ts}')
    if sync_version_json(version, ts):
        print(f'+ version.json synced to {version} / {ts}')
    else:
        print('  version.json already up to date')
    print('Done.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
