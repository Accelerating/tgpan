#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
. "${project_dir}/scripts/common/runtime.sh"
check_runtime
stop_backend
build_backend
start_backend
