#!/usr/bin/env python3
"""Resolve GitOps SemVer image tags into immutable image digests during CI only."""
import argparse
import re
import subprocess
from pathlib import Path

import yaml

TAGGED = re.compile(r"^(ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+):(v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def pin(docs, expected_version, resolve):
    seen = {}
    count = 0
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get('kind')
        if kind == 'Deployment' or kind == 'StatefulSet' or kind == 'DaemonSet' or kind == 'Job':
            pod = (((doc.get('spec') or {}).get('template') or {}).get('spec') or {})
        elif kind == 'Pod':
            pod = doc.get('spec') or {}
        else:
            continue
        for container in list(pod.get('containers') or []) + list(pod.get('initContainers') or []):
            value = container.get('image')
            m = TAGGED.fullmatch(value or '')
            if not m or m.group(2) != expected_version:
                raise ValueError('Every workload image must use the selected strict SemVer version')
            ref = m.group(0)
            if ref not in seen:
                if len(seen) >= 32:
                    raise ValueError('Too many images in one release')
                digest = resolve(ref)
                if not DIGEST.fullmatch(digest):
                    raise ValueError(f'Invalid registry digest for {m.group(1)}')
                seen[ref] = digest
            container['image'] = f'{m.group(1)}@{seen[ref]}'
            count += 1
    if count == 0:
        raise ValueError('No workload images found')
    return docs, seen


def oras_resolve(ref):
    result = subprocess.run(['oras', 'resolve', ref], text=True, capture_output=True, timeout=30, check=True)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)',args.version):
        raise ValueError('Invalid SemVer tag')
    docs=list(yaml.safe_load_all(args.input.read_text(encoding='utf-8')))
    pinned, refs=pin(docs,args.version,oras_resolve)
    args.output.write_text(yaml.safe_dump_all(pinned,sort_keys=False),encoding='utf-8')
    print(f'Pinned {len(refs)} distinct GHCR images for {args.version}')


if __name__ == '__main__':
    main()
