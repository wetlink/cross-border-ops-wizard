#!/usr/bin/env python3
"""Conservative public-material checks, not a comprehensive secret scanner."""
import ipaddress
import re
import subprocess
from pathlib import Path


# Public DNS examples and a historical synthetic test fixture, not customer exits.
PUBLIC_EXAMPLES = {'1.1.1.1', '8.8.8.8', '9.9.9.9', '119.29.29.29', '202.96.209.133', '1.2.3.4'}
DOC_NETS = [ipaddress.ip_network(n) for n in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]
IP_RE = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
LINK_ID = re.compile(r'vless://([0-9a-fA-F-]{36})@')
PERSONAL_EMAIL = re.compile(r'[\w.+-]+@(?:gmail|qq|163|outlook|hotmail)\.com', re.I)


def findings(text):
    result = set()
    for value in IP_RE.findall(text):
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.is_global and value not in PUBLIC_EXAMPLES and not any(ip in n for n in DOC_NETS):
            result.add('non-example public IPv4')
    for identity in LINK_ID.findall(text):
        if not identity.startswith('00000000-0000-4000-8000-'):
            result.add('non-fixture VLESS identity')
    if PERSONAL_EMAIL.search(text):
        result.add('personal mailbox')
    if re.search('/' + r'Users/[^\s/]+/', text):
        result.add('machine-local user path')
    if re.search(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----', text):
        result.add('private key block')
    if re.search(r'(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}', text):
        result.add('GitHub token')
    return sorted(result)


def main():
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).decode().split('\0')
    failures = []
    for name in sorted(set(names) - {''}):
        path = root / name
        if not path.is_file():
            continue
        if path.suffix in ('.env', '.pem', '.key', '.db', '.sqlite', '.pyc'):
            failures.append((name, 'private or compiled artifact'))
            continue
        for issue in findings(path.read_text(encoding='utf-8')):
            failures.append((name, issue))
    for name, issue in failures:
        print(f'{name}: {issue}')  # Never print the detected value.
    print(f'Public-material checks: {len(failures)} findings')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
