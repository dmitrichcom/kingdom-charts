#!/bin/sh
set -eu
python3 -m unittest discover -s ops/shadow -p 'test_*.py' -v
