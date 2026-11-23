#!/bin/sh
set -eu
if ! command -v helm >/dev/null 2>&1; then
  echo 'Helm is required to run the chart gate' >&2
  exit 75
fi
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  echo 'Python with PyYAML is required to run the chart gate' >&2
  exit 75
fi
python3 -m unittest discover -s tests -p 'test_*.py'
