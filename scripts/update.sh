#!/bin/sh
set -eu
umask 022

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
. "${project_dir}/scripts/common/runtime.sh"
if [ "$#" -ne 0 ]; then
    echo "用法：$0" >&2
    exit 1
fi
check_runtime
command -v git >/dev/null 2>&1 || { echo "缺少命令：git" >&2; exit 1; }
cd "${project_dir}"
if [ -n "$(git status --porcelain)" ]; then
    echo "工作区有未提交或未跟踪文件，请先处理后再更新" >&2
    exit 1
fi
# Reject detached HEAD and missing upstream before stopping the service.
git symbolic-ref --quiet HEAD >/dev/null
git rev-parse --verify '@{upstream}' >/dev/null
command -v systemctl >/dev/null 2>&1 || { echo "缺少命令：systemctl" >&2; exit 1; }
service_dir=$(systemctl show tgpan.service --property=WorkingDirectory --value)
if [ "${service_dir}" != "${backend_dir}" ]; then
    echo "tgpan.service 的工作目录不属于本项目，拒绝更新" >&2
    exit 1
fi
systemctl stop tgpan.service

# Do not restart on failure: dependency or database versions may no longer match.
trap 'echo "更新未完成，请检查错误和 tgpan.service 状态；处理问题后可重新运行更新脚本。" >&2' 0

echo "拉取当前分支的远程最新代码…"
GIT_TERMINAL_PROMPT=0 git pull --ff-only
# Load the runtime helpers shipped with the new revision.
. "${project_dir}/scripts/common/runtime.sh"
build_backend --no-dev
systemctl start tgpan.service
systemctl is-active --quiet tgpan.service
trap - 0
echo "更新完成，tgpan.service 已启动；日志：journalctl -u tgpan"
