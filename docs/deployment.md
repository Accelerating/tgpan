# 运行与部署

## 本地开发

需要 PostgreSQL 16+、Python 3.13、uv、Node.js 22 或更新版本及 pnpm 10.32.1。在项目根目录复制 `.env.example` 为 `.env`，无需申请 Telegram 应用凭据；本地 HTTP 开发要把 `TGPAN_PUBLIC_ORIGIN` 留空、`TGPAN_SECURE_COOKIE=false`。后端从自身工作目录读取 `.env`，可复制同一份到 `backend/.env`（该文件已忽略），或把环境变量导出到进程。Docker Compose 则读取根目录 `.env` 并注入容器。

先使用数据库管理员创建专用账号与数据库（替换示例密码）：

```sql
CREATE ROLE tgpan LOGIN PASSWORD 'change_me';
CREATE DATABASE tgpan OWNER tgpan;
```

在 `.env` 设置 `DATABASE_URL=postgresql://tgpan:change_me@127.0.0.1:5432/tgpan`。本机与远程 PostgreSQL 都使用此配置；账号需拥有该库的建表权限，无需超级用户权限。密码中的特殊字符需 URL 编码。数据库表结构在启动时自动初始化和更新。密钥、在途上传及离线文件保存在 `TGPAN_DATA_DIR`，后端使用单 worker。

```sh
cd backend
uv sync --locked
uv run python -m app.cli create-admin --username admin
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

管理员命令交互输入密码，没有预置密码。另开终端：

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

使用 Vite 打印的地址访问。`/api` 代理到 127.0.0.1:8000，前端与 API 仍是同源请求。本地上传请使用 localhost 或 127.0.0.1；远程部署请使用 HTTPS。

## 本地合并运行

在项目根目录执行：

```sh
./scripts/build-frontend.sh
cd backend
uv sync --locked --no-dev
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

脚本将 `frontend/dist` 复制到 `backend/static`。浏览器访问 http://127.0.0.1:8000 即可。只能运行一个 Uvicorn worker，不要开启自动多进程扩容。

## 一键本地重启

从项目根目录执行：

```sh
./scripts/restart.sh
```

脚本先停止当前端口上、工作目录为本项目 backend 且启动命令为 Uvicorn `app.main:app` 的后端进程，再调用公共构建脚本安装前端依赖、构建并复制到 `backend/static`，同步后端依赖，最后在前台启动服务。可以从任意工作目录使用脚本的绝对路径执行。

默认访问 http://127.0.0.1:8000，按 Ctrl+C 停止；首次使用仍需先创建管理员。需要 uv、pnpm、python3、lsof。依赖安装采用非交互模式，可以从无 TTY 的终端运行。构建或依赖安装失败时不会继续启动；旧进程 30 秒内未退出则中止，不强制杀进程。端口被其他项目占用时拒绝关闭它。

可通过环境变量指定监听地址与端口：

```sh
TGPAN_HOST=127.0.0.1 TGPAN_PORT=8001 ./scripts/restart.sh
```

TGPAN_PORT 同时用于寻找需要停止的旧进程；更改端口前，应先停止旧端口的服务。此脚本用于本地直接运行，Docker 部署使用 Docker Compose 管理。

## systemd + Caddy 原生部署

原生部署适合没有 Docker、内存约 1GB 的 VPS。首次部署可在开发机器构建前端并上传产物，后续一键更新在服务器构建；运行时由 Python 后端提供 API 和静态文件。仓库内提供 `deploy/tgpan.service` 和 `deploy/Caddyfile.example`。不要将本地 `.env`、数据库、Bot Token 或密钥复制到服务器。

目录约定：

| 路径 | 用途 |
| --- | --- |
| `/opt/tgpan` | 从 GitHub 克隆的代码及后端虚拟环境 |
| `/opt/tgpan/backend/static` | 与代码版本对应的前端生产构建 |
| `/opt/tgpan-python` | uv 管理的 Python 3.13，服务用户需要读取和执行权限 |
| `/etc/tgpan/tgpan.env` | root 所有、权限 600 的服务环境配置 |
| `/var/lib/tgpan` | `tgpan` 服务用户所有、权限 700 的数据库、密钥及上传临时文件 |

服务器安装 Git 和 uv，创建无登录权限的 `tgpan` 系统用户，然后准备代码和运行时：

```sh
git clone --branch main https://github.com/Accelerating/tgpan.git /opt/tgpan
UV_PYTHON_INSTALL_DIR=/opt/tgpan-python uv python install 3.13
cd /opt/tgpan/backend
UV_PYTHON_INSTALL_DIR=/opt/tgpan-python uv sync --locked --no-dev --python 3.13
```

在本地 `frontend` 执行 `pnpm install --frozen-lockfile && pnpm build`，将 `dist/` 内容复制到服务器的 `/opt/tgpan/backend/static/`。前端产物必须与服务器使用同一源码版本，更新时先构建完整的新目录，再替换旧目录。

创建 `/etc/tgpan/tgpan.env`，其余参数使用代码默认值：

```dotenv
TGPAN_DATA_DIR=/var/lib/tgpan
TGPAN_STATIC_DIR=/opt/tgpan/backend/static
TGPAN_PUBLIC_ORIGIN=https://pan.zhcn.win
TGPAN_SECURE_COOKIE=true
TGPAN_TRUSTED_PROXIES=127.0.0.1/32,::1/128
TGPAN_ENABLE_API_DOCS=false
TGPAN_PROXY_URL=
```

在 `/opt/tgpan/backend` 中以服务用户初始化管理员：

```sh
runuser -u tgpan -- env TGPAN_DATA_DIR=/var/lib/tgpan \
  /opt/tgpan/backend/.venv/bin/python -m app.cli create-admin --username admin
install -m 0644 /opt/tgpan/deploy/tgpan.service /etc/systemd/system/tgpan.service
systemctl daemon-reload
systemctl enable --now tgpan
curl -fsS http://127.0.0.1:8000/api/health
```

服务仅监听 `127.0.0.1:8000`，单 worker，内存上限 512MB，开机启动，异常退出自动重启；数据目录在代码目录外，更新代码不会覆盖数据。日志使用 `journalctl -u tgpan` 查看。原生部署使用 `scripts/update.sh` 更新，脚本通过 systemd 管理服务；`scripts/restart.sh` 用于本地前台运行。

将 `deploy/Caddyfile.example` 的站点块加入现有 Caddyfile。`header_up X-Forwarded-For {remote_host}` 使用直连客户端地址覆盖用户提交的转发头，与后端仅信任回环代理的设置配套。Caddy 自动管理证书及 HTTP 到 HTTPS 跳转；80/443 端口需可访问。先备份原配置并使用正在运行的同一个 Caddy 二进制校验，再平滑重载，保留原有站点和全局配置。

dedione 的部署约定是 `/opt/tgpan`，域名为 `pan.zhcn.win`；现有 Caddy 二进制为 `/root/naive/caddy`，配置为 `/root/naive/Caddyfile`，由 `caddy.service` 管理：

```sh
/root/naive/caddy validate --config /root/naive/Caddyfile --adapter caddyfile
systemctl reload caddy
systemctl status tgpan --no-pager
curl -fsS https://pan.zhcn.win/api/health
```

首次自动部署时，管理员为 `admin`，随机初始密码仅保存在服务器 `/etc/tgpan/admin-initial-password`，root 所有、权限 600。管理员可通过 `ssh dedione 'cat /etc/tgpan/admin-initial-password'` 读取，登录后在设置中修改密码，随后删除此文件；密码不会写入仓库。Telegram 存储配置由管理员在网页中添加。

后续生产更新统一使用一键更新脚本。先按下文备份 PostgreSQL 数据库和数据目录，然后使用有代码写入权限及 systemd 服务管理权限的部署账号执行（通常为 root）：

```sh
UV_PYTHON_INSTALL_DIR=/opt/tgpan-python NODE_OPTIONS=--max-old-space-size=384 /opt/tgpan/scripts/update.sh
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS https://pan.zhcn.win/api/health
```

脚本依次停止 `tgpan.service`、对当前分支执行 `git pull --ff-only`、安装前端依赖并构建和复制静态文件、执行 `uv sync --locked --no-dev`，最后启动服务并检查 systemd 活动状态。后端启动时自动执行数据库表结构升级。服务配置和运行环境继续由 systemd 加载，无需把生产环境配置复制到 `backend/.env`。

服务器需安装 Git、uv、Node.js、pnpm、python3 和 lsof，并配置 Git 远程仓库的非交互读取权限；一键更新会在服务器构建前端，1GB VPS 需确保足够的可用内存；上述命令限制 Node.js 堆为 384MiB，dedione 已验证构建成功。可从任意目录使用脚本绝对路径运行。脚本确认服务工作目录属于本项目，并在停止服务前拒绝未提交或未跟踪文件；仓库必须处于有上游分支的正常分支。分支分叉时拒绝合并，不自动覆盖或暂存本地改动。

拉取、构建或依赖同步失败时不会继续启动服务，解决错误后重新运行脚本。启动失败使用 `journalctl -u tgpan` 排查；脚本不自动回退代码或数据库，也不自动修改 systemd 单元文件。若发布包含单元配置变更，需另行安装单元并执行 `systemctl daemon-reload`。备份 `/var/lib/tgpan` 时先停止服务，确保同时保留 `secret.key` 和在途上传、离线文件。

源码检出和前端目录须允许 `tgpan` 用户读取和遍历。Git 更新及前端展开使用 `umask 022`，代码目录和文件通常为 755/644；备份目录使用 700，配置、密钥和备份归档使用 600，不能把备份的 `umask 077` 全局沿用到 Git 检出。发布前可执行以下检查，确认服务用户可以导入新代码：

```sh
cd /opt/tgpan/backend
runuser -u tgpan -- env PYTHONDONTWRITEBYTECODE=1 \
  /opt/tgpan/backend/.venv/bin/python -c 'import app.main'
```

## Docker Compose 部署 VPS

1. 在根目录复制 `.env.example` 到 `.env`，填写实际 `TGPAN_PUBLIC_ORIGIN=https://你的域名`，保留 `TGPAN_SECURE_COOKIE=true`。
2. 构建并初始化管理员：

```sh
docker compose build
docker compose run --rm app /app/.venv/bin/python -m app.cli create-admin --username admin
docker compose up -d
```

3. 反向代理将域名转发到 `127.0.0.1:8000`。容器端口默认仅绑定本机，避免绕过 HTTPS 直接暴露。
4. 登录页面，在设置中添加机器人配置并运行连接测试，通过后先用小文件验证上传下载，再验证大文件。

Docker 多阶段构建在 Node 阶段构建前端，在 Python 阶段只保留后端、虚拟环境和静态文件；运行时不需要 Node 服务。数据保存到命名卷 `tgpan-data`，容器以 UID/GID 10001 非 root 用户运行。重建镜像和普通 `docker compose down` 保留数据；不要执行 `docker compose down -v`。

1 核 1GB 的 VPS 建议在本地或 CI 构建镜像再传到 VPS，避免 Node 构建占用运行内存。构建机 CPU 架构应与 VPS 一致，或通过 buildx 指定对应平台。Compose 运行内存限制 512MB，单核，日志轮转；保留磁盘给操作系统、镜像、PostgreSQL 和备份。2GiB 只是临时上传目录上限，不是整个数据卷的配额。

### Nginx 示例

以下配置位于已启用 TLS 的 server 块中，证书由你现有的 HTTPS 配置管理：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    client_max_body_size 5m;
    proxy_request_buffering off;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

每次上传只有 4MiB HTTP 分块，无需允许 5GB 的单个 HTTP 请求。关闭请求与响应缓冲，避免代理把大文件缓存到磁盘。通过显式 `TGPAN_PUBLIC_ORIGIN` 校验浏览器来源；反向代理须保留 Host。

Nginx 必须用 `$remote_addr` 覆盖外部提交的 `X-Forwarded-For`，不要直接转发客户端提供的值。`TGPAN_TRUSTED_PROXIES` 填后端实际看到的代理 IP/CIDR，逗号分隔；留空时不信任转发头。本机 Nginx 直连可填 `127.0.0.1/32,::1/128`；宿主机 Nginx 转发进 Docker 时，通常应填容器网络的网关地址，例如 `172.18.0.1/32`，须通过 `docker inspect $(docker compose ps -q app)` 的 `NetworkSettings.Networks.*.Gateway` 确认后写入 `.env` 并重建应用容器。不要使用所有来源通配符或猜测网关，未正确配置时限流仍会把代理后的连接视为同一来源。

Docker 与本地启动脚本均禁用 Uvicorn 自动处理转发头，由应用统一校验可信代理。若前面还有负载均衡器，应先在 Nginx 中仅信任该负载均衡器并恢复客户端地址，再向后端发送清洗后的单一地址。

## 配置

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `DATABASE_URL` | 必填 | PostgreSQL 连接 URL，专用账号需拥有数据库 |
| `TGPAN_DATA_DIR` | `data`，容器 `/data` | 持久化数据目录 |
| `TGPAN_STATIC_DIR` | 后端 `static` | 前端构建目录 |
| `TGPAN_PROXY_URL` | 空 | 可选 Telegram 代理 |
| `TGPAN_PUBLIC_ORIGIN` | 空 | 公网精确来源，含协议和非默认端口 |
| `TGPAN_SECURE_COOKIE` | `false` | HTTPS 部署须设为 true |
| `TGPAN_TRUSTED_PROXIES` | 空 | 可读取转发头的代理 IP/CIDR，逗号分隔 |
| `TGPAN_ENABLE_API_DOCS` | `false` | 仅本地开发需要时显式开启接口文档 |
| `TGPAN_MAX_FILE_SIZE` | `5000000000` | 最大逻辑文件字节数 |
| `TGPAN_CHUNK_SIZE` | `4194304` | HTTP 上传分块字节数 |
| `TGPAN_BLOCK_SIZE` | `16777216` | Telegram 存储块字节数 |
| `TGPAN_TEMP_LIMIT` | `2147483648` | 临时上传目录上限 |
| `TGPAN_UPLOAD_TTL` | `86400` | 未完成接收/失败任务无活动保留秒数 |
| `TGPAN_SESSION_DAYS` | `7` | 登录会话天数 |

首次运行后不要直接改变块大小，会改变在途任务偏移解释。修改传输参数前，先完成或取消所有未完成上传；已有完成文件的下载根据实际块长度读取。

## 备份与恢复

数据库不存文件内容，但存目录、配置、进度及消息映射。`secret.key` 丢失会导致 Token 无法解密。备份应加密并保管在服务器之外。

完整备份应停止后端，使用 PostgreSQL 客户端工具备份数据库，同时备份数据目录中的 `secret.key`、`uploads/` 和 `offline/`。数据库备份不能替代密钥和在途文件备份。客户端主版本须不低于服务端版本。

```sh
# DATABASE_URL 已导出到当前 shell；配置文件不会自动导入 shell。
pg_dump --dbname="$DATABASE_URL" --format=custom --file=tgpan.dump
# 恢复到新建的空库，连接配置指向该库：
pg_restore --dbname="$DATABASE_URL" --no-owner --no-acl tgpan.dump
```

忘记密码：

```sh
cd backend
uv run python -m app.cli reset-password --username admin
```

## 数据库自动升级

部署新代码并启动后端时，应用读取 `schema_version`，按版本顺序执行缺少的 PostgreSQL 升级脚本，然后更新版本号；已执行的版本不会重复执行。新库自动创建表并升级到代码支持的最新版本，无需手工运行 SQL。

发布涉及表结构的功能时，在 `backend/app/common/migrations/` 新增连续编号的 SQL 脚本，例如 `002_add_description.sql`，不要修改已发布的 `schema.sql` 或已有升级脚本。脚本规则见该目录的 [说明](../backend/app/common/migrations/README.md)。升级使用应用数据库账号，因此账号须有相应表结构修改权限。

升级前停止旧服务并按备份流程备份数据库和数据目录。初始化及升级由数据库事务锁串行执行，所有待升级脚本与版本号更新在同一个事务内提交。失败时全部回滚，后端停止启动；检查启动日志、修复问题后重新启动即可重试。数据库版本高于代码支持范围时拒绝启动，不会自动降级。回退旧代码前评估表结构兼容性，必要时恢复升级前备份。

## 验证

```sh
cd backend
uv sync --locked
uv run pytest -q
```

前端在 `frontend` 执行 `pnpm build`，包含 TypeScript 检查；`pnpm test:i18n` 验证浏览器语言选择、英文回退、翻译目录、插值、接口语言和日期格式；`pnpm test:security` 验证依赖补丁阻止原型污染且不影响正常主题合并。前端依赖补丁位于 `frontend/patches`，必须与锁文件一起提交，Docker 在安装依赖前复制该目录。

测试使用 `DATABASE_URL` 指向的数据库，每项测试创建随机临时 schema 并在结束时删除，仅清理自己创建的数据；账号需有建 schema 权限，无需单独配置测试库。

`/api/health` 用于容器健康检查；`/api/docs` 和 `/api/openapi.json` 默认返回 404，只有本地开发显式设置 `TGPAN_ENABLE_API_DOCS=true` 后才提供接口文档。业务数据接口仍要求登录。测试使用模拟 Telegram 存储，真实 Bot Token 测试需在配置页面执行。

## 本机代理

本机访问 Telegram 通过 HTTP 代理 `http://127.0.0.1:7897`，已配置在不纳入版本控制的 `backend/.env` 中：

```dotenv
TGPAN_PROXY_URL=http://127.0.0.1:7897
```

这是当前开发机器的地址，VPS 必须使用其自身可达的代理地址；能直连时留空。容器中的 `127.0.0.1` 指容器自身，不能直接指向宿主机代理，容器测试需填写容器可达的宿主机地址。支持 HTTP、HTTPS、SOCKS5 代理。应用不自动使用进程的 HTTP_PROXY/HTTPS_PROXY 环境变量。

Bot API 最大下载 20MB，因此存储块默认 16MiB，配置上限也是 16MiB。旧版本如有设置 `TGPAN_BLOCK_SIZE=67108864`，需要改为 `16777216` 并先结束或取消旧上传。之前的模拟测试数据可删除后重建；旧 MTProto 文件记录没有 Bot API file_id，不能直接作为本版本下载记录使用。不要删除真实文件记录来尝试修复凭据问题。

## 离线下载组件（Linux 原生 / macOS）

离线下载只需要 aria2，不需要 ffmpeg。管理员登录后在“设置 → 离线下载组件”检查安装状态；没有安装时点击“安装应用管理版本”，已有应用管理版本时点击“更新 aria2”。支持 glibc Linux x86_64/ARM64 及 macOS Intel/Apple Silicon。安装通过官方 micromamba 引导和 conda-forge 获取 aria2 及其运行库，不要求 apt、brew、编译工具或 root；需要部署机器能访问 `micro.mamba.pm`、其下载重定向目标及 conda-forge 软件包服务。安装缓存和环境会占用额外磁盘空间。

原生 systemd 配置的 `StateDirectory=tgpan` 可写，组件和下载文件都放在 `/var/lib/tgpan`，不需要开放 `/usr` 或修改 `NoNewPrivileges`。服务用户的 home 应同样设为 `/var/lib/tgpan`（dedione 已如此配置），以便 micromamba 创建 `.conda/environments.txt` 环境登记文件；不要将它指向被 `ProtectHome` 隔离的 `/home` 或 `/root`。更新前暂停离线任务；保持现有单 Uvicorn worker 设置。BT 的主动连接、DHT 和 tracker 需要服务器可访问公网；要改善入站 Peer 连通性，可按 aria2 默认端口策略配置服务器防火墙，应用不自动修改防火墙。

也可手动安装系统的 `aria2c`，macOS 例如 `brew install aria2`，并确保后端进程的 PATH 包含其安装目录。应用管理版本优先于系统版本；网页更新不会升级系统包。完整功能与磁盘策略见 [离线下载](features/offline.md)。

默认单文件仍最大 5GB；离线容量默认 10GiB、磁盘保留默认 512MiB，后两项在网页设置中修改并保存到 PostgreSQL。`TGPAN_TEMP_LIMIT` 仍仅限制公共上传块缓存，不承担完整离线文件容量。备份须包含 `offline/` 中的在途文件与控制文件。`components/` 中的独立环境包含绝对安装路径，换机器或改变数据目录路径后应重新安装组件；数据库、密钥、上传和离线数据仍按原备份流程恢复。

## 视频下载组件

视频下载需独立的 yt-dlp 与 ffmpeg 命令，项目 Python 环境不安装 yt-dlp。管理员可在设置页的“视频下载组件”分别安装应用管理版本（yt-dlp 环境同时安装 Deno），或自行安装并确保服务 PATH 中能找到 `yt-dlp`、`ffmpeg`、`ffprobe` 和 Deno。应用组件位于 `TGPAN_DATA_DIR/components`，需要写权限和足够磁盘；使用 systemd 或 Docker 时也须保证服务环境可见系统命令。组件更新前暂停活动下载及转存。

升级时自动执行数据库版本 2 的迁移，新增 Cookie 和视频元数据表；按正常流程备份 PostgreSQL 与数据目录中的密钥，再部署新代码。使用方式和资源限制见[视频下载](features/videos.md)。
