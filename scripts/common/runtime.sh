#!/bin/sh
# Shared by restart.sh and update.sh; project_dir is set by the entrypoint.
backend_dir="${project_dir}/backend"
service_host=${TGPAN_HOST:-127.0.0.1}
service_port=${TGPAN_PORT:-8000}

check_runtime() {
    case "${service_port}" in
        ''|*[!0-9]*) echo "TGPAN_PORT 必须是 1～65535 的整数" >&2; exit 1 ;;
    esac
    if [ "${service_port}" -lt 1 ] || [ "${service_port}" -gt 65535 ]; then
        echo "TGPAN_PORT 必须是 1～65535 的整数" >&2
        exit 1
    fi
    for command_name in uv pnpm python3 lsof; do
        command -v "${command_name}" >/dev/null 2>&1 || {
            echo "缺少命令：${command_name}，请先安装" >&2
            exit 1
        }
    done
}

stop_backend() {
    # Identify both the working directory and command before stopping a port listener.
    pids=$(lsof -nP -t -iTCP:"${service_port}" -sTCP:LISTEN 2>/dev/null || true)
    for pid in ${pids}; do
        process_dir=$(lsof -a -p "${pid}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
        process_command=$(ps -p "${pid}" -o args=)
        case "${process_command}" in
            *uvicorn*app.main:app*) ;;
            *) echo "端口 ${service_port} 被其他服务占用，拒绝关闭 PID ${pid}" >&2; exit 1 ;;
        esac
        if [ "${process_dir}" != "${backend_dir}" ]; then
            echo "端口 ${service_port} 不属于本项目，拒绝关闭 PID ${pid}" >&2
            exit 1
        fi
    done
    for pid in ${pids}; do
        echo "停止后端进程 ${pid}…"
        kill -TERM "${pid}"
        attempts=0
        while kill -0 "${pid}" 2>/dev/null; do
            if [ "${attempts}" -ge 30 ]; then
                echo "进程 ${pid} 未在 30 秒内退出，已停止重启流程" >&2
                exit 1
            fi
            sleep 1
            attempts=$((attempts + 1))
        done
    done
}

build_backend() {
    echo "重新构建前端并复制静态文件…"
    "${project_dir}/scripts/build-frontend.sh"

    cd "${backend_dir}"
    echo "同步后端依赖…"
    uv sync --locked "$@"
}

start_backend() {
    echo "启动后端：http://${service_host}:${service_port}（Ctrl+C 停止）"
    exec uv run --no-sync uvicorn app.main:app --host "${service_host}" --port "${service_port}" \
        --workers 1 --no-proxy-headers --timeout-graceful-shutdown 20
}
