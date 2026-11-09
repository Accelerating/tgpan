# 技术栈和结构

后端：Python 3.13、FastAPI、Uvicorn、HTTPX + 官方云端 Telegram Bot API，使用 uv 和 uv.lock 锁定依赖。数据库使用 PostgreSQL 16+，通过 psycopg 连接池访问；以 `schema_version` 表管理版本，事务及 advisory lock 保证初始化和升级串行，数据库版本高于代码支持范围时拒绝启动。密码用 Argon2id，Bot Token 用 Fernet 加密。

预览与下载共用 `files/delivery.py` 的鉴权、Range 解析及跨块流式输出，允许预览的媒体类型统一在 `files/media.py` 定义。文件列表返回 preview_kind，前端不重复维护类型清单。

前端：React 19、TypeScript、Vite、HeroUI 2、Tailwind CSS 4、Lucide 图标，使用 pnpm 和 pnpm-lock.yaml。采用浅色侧边栏布局，适配手机；支持中文和英文，按浏览器语言选择，未匹配时使用英文。普通 API 使用 application/json；上传分块与下载使用 application/octet-stream。

```text
backend/
  app/
    common/       配置、数据库、密钥、会话依赖、可信来源、并发限流与国际化
    accounts/     登录与帐号管理
    files/        目录与文件记录、回收站、媒体类型和公共流式读取
    shares/       分享链接、密码访问会话、有效期与公开读取授权
    storage/      存储接口、Bot API 实现、配置管理
    transfers/    浏览器与本地文件的公共分块转存、任务恢复、流式下载、后台清理
    offline/      离线下载调度、aria2 子进程、种子清单与受限 HTTP 转发
    components/   aria2 检测、独立安装和更新
    main.py       应用生命周期和静态文件入口
    cli.py        管理员初始化、密码重置
  tests/          使用模拟存储的集成测试
  static/         构建产物（由脚本或镜像构建生成）
frontend/src/
  components/     通用弹窗、响应式操作菜单、文件图标与状态展示
  i18n/           语言匹配、翻译目录、插值与数字格式化
  lib/            API、类型、查询与上传队列
  pages/          登录、文件、传输、设置、用户管理、分享管理及独立分享访问页
scripts/          前端构建、本地重启、systemd 一键更新及公共运行模块
deploy/           原生 systemd 服务和 Caddy 反向代理模板
```

后端只有一个 Uvicorn worker。应用通过文件锁禁止同一数据目录启动多个实例；后台任务在同一个事件循环中运行，不依赖 Redis 或 Celery。默认一个远程上传任务、一个下载任务。PostgreSQL 事务保持简短，文件流使用有界缓冲，不把整个文件装入内存。

核心记录：`nodes` 维护目录树、名称和回收站状态；`uploads` 维护文件大小、上传进度、指纹和绑定配置；`blocks` 维护有序文件块、消息 ID、Bot API file_id 和 SHA256；`cleanup` 在文件元数据永久删除后保留远程清理所需的信息。

文件夹上传通过 `files/folders.py` 在事务中解析目录路径，前端 `lib/folderUpload.ts` 统一处理选择器和拖放的目录树，再复用现有分块传输队列。目录分享在 `shares/service.py` 中逐级检查当前父目录链，限制浏览与文件读取的范围，并在流输出期间复查授权。未来打包下载可按目录遍历有序读取文件。业务层通过 `Storage` 协议访问存储，不依赖 Telegram 的目录概念。

PostgreSQL 初始表结构版本为 1，`common/schema.sql` 定义初始结构，后续升级脚本放在 `common/migrations/`，按 `002_description.sql`、`003_description.sql` 连续编号。启动时从当前版本依次执行所有待升级脚本，新库从初始结构开始执行。所有待升级脚本及版本号更新共用一个事务，任意脚本失败则全部回滚并停止启动；同一版本不会重复执行。已发布脚本保持不变，后续表结构或数据转换通过新增脚本实现。文件块的 `file_id` 用于 getFile，消息 ID 单独用于删除，不通过频道消息 ID 猜测下载地址。升级脚本需明确处理已有数据，不自动推断字段变更。

`common/limits.py` 统一处理可信代理地址、尝试次数预留和无等待队列的并发限制；登录会话创建在写事务内重新检查凭据快照。`transfers/receiving.py` 负责接收容量预留和清理，网络接收不持有全局修改锁。连接测试使用独立并发名额及配置占用标记。接口文档默认关闭，公开文件读取不返回存储诊断。

HeroUI 的间接依赖 `deepmerge@4.3.1` 通过 pnpm 补丁同时约束源文件和 CJS/UMD 入口，在输入两侧忽略原型相关特殊键；补丁与锁文件一起维护，正常主题合并与攻击输入有独立测试。

界面仅保留页面标题、操作、状态和必要的输入/风险提示；不展示宣传语、英文装饰标题、侧栏介绍卡片或重复的功能说明。登录页为单栏表单。

文件名正文采用 14px，表头与元信息采用 12px，次要文字颜色由公共 CSS 变量统一维护。桌面文件行高为 56px，手机端为 64px；文件面板按内容撑高。`ActionMenu` 在桌面展示快捷按钮，在手机展示同一组操作的下拉菜单，复用操作回调与禁用状态。

`lib/dragAndDrop.ts` 统一处理站内项目拖动的数据与目标状态，并区分电脑文件拖入；文件页复用批量移动接口完成目录映射更新。同名检查和整组移动事务封装在后端 `files/service.py`，不调用存储服务。

`shares` 和 `share_sessions`，保存分享标题、加密令牌、密码哈希、有效期及访客授权。私有文件与分享公开读取通过不同入口鉴权，共用 `files/delivery.py`；媒体组件 `MediaViewer` 同时用于私人预览和分享页。

离线任务由 `offline/` 独立持久化和调度，通过系统命令调用 aria2 并解析进度，不使用 RPC。完整文件下载后经 `transfers/local.py` 导入同一 Telegram 块队列；任务、单文件状态与上传记录关联，确认索引提交后清理本地原始文件。`uploads.origin` 区分浏览器上传与离线转存。组件使用数据目录中的独立环境，更新验证成功后原子切换，不需要 root。详情见 [离线下载](features/offline.md)。
