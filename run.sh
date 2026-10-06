#! /usr/bin/env bash
set -euxo nounset -o pipefail
(( UID ))
(( ! $# ))
[[ -n ${VIRTUAL_ENV:-} ]] ||
. ~/venv/bin/activate
#python app.py
python -m juniper_lc.app
