#!/usr/bin/env bash

set -e

pytest --snapshot-update -m 'not slow'
pytest -vvv -m 'not slow' .
