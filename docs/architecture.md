# 技术栈和结构

后端：Python 3.13、FastAPI、Uvicorn、HTTPX + 官方云端 Telegram Bot API，使用 uv 和 uv.lock 锁定依赖。数据库使用 Python 自带 sqlite3，开启外键及 WAL；通过 `PRAGMA user_version` 管理版本迁移，未知版本拒绝启动。密码用 Argon2id，Bot Token 用 Fernet 加密。

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
    transfers/    上传分块、任务恢复、流式下载、后台清理
    main.py       应用生命周期和静态文件入口
    cli.py        管理员初始化、密码重置、数据库备份
  tests/          使用模拟存储的集成测试
  static/         构建产物（由脚本或镜像构建生成）
frontend/src/
  components/     通用弹窗、响应式操作菜单、文件图标与状态展示
  i18n/           语言匹配、翻译目录、插值与数字格式化
  lib/            API、类型、查询与上传队列
  pages/          登录、文件、传输、设置、用户管理、分享管理及独立分享访问页
scripts/          前端构建与复制脚本
deploy/           原生 systemd 服务和 Caddy 反向代理模板
```

后端只有一个 Uvicorn worker。应用通过文件锁禁止同一数据目录启动多个实例；后台任务在同一个事件循环中运行，不依赖 Redis 或 Celery。默认一个远程上传任务、一个下载任务。SQLite 事务保持简短，文件流使用有界缓冲，不把整个文件装入内存。

核心记录：`nodes` 维护目录树、名称和回收站状态；`uploads` 维护文件大小、上传进度、指纹和绑定配置；`blocks` 维护有序文件块、消息 ID、Bot API file_id 和 SHA256；`cleanup` 在文件元数据永久删除后保留远程清理所需的信息。

文件夹上传通过 `files/folders.py` 在事务中解析目录路径，前端 `lib/folderUpload.ts` 统一处理选择器和拖放的目录树，再复用现有分块传输队列。目录分享在 `shares/service.py` 中逐级检查当前父目录链，限制浏览与文件读取的范围，并在流输出期间复查授权。未来打包下载可按目录遍历有序读取文件。业务层通过 `Storage` 协议访问存储，不依赖 Telegram 的目录概念。

当前数据库版本为 3；文件块的 `file_id` 用于 getFile，消息 ID 单独用于删除，不通过频道消息 ID 猜测下载地址。迁移自动执行并保留现有数据。

`common/limits.py` 统一处理可信代理地址、尝试次数预留和无等待队列的并发限制；登录会话创建在写事务内重新检查凭据快照。`transfers/receiving.py` 负责接收容量预留和清理，网络接收不持有全局修改锁。连接测试使用独立并发名额及配置占用标记。接口文档默认关闭，公开文件读取不返回存储诊断。

HeroUI 的间接依赖 `deepmerge@4.3.1` 通过 pnpm 补丁同时约束源文件和 CJS/UMD 入口，在输入两侧忽略原型相关特殊键；补丁与锁文件一起维护，正常主题合并与攻击输入有独立测试。

界面仅保留页面标题、操作、状态和必要的输入/风险提示；不展示宣传语、英文装饰标题、侧栏介绍卡片或重复的功能说明。登录页为单栏表单。

文件名正文采用 14px，表头与元信息采用 12px，次要文字颜色由公共 CSS 变量统一维护。桌面文件行高为 56px，手机端为 64px；文件面板按内容撑高。`ActionMenu` 在桌面展示快捷按钮，在手机展示同一组操作的下拉菜单，复用操作回调与禁用状态。

`lib/dragAndDrop.ts` 统一处理站内项目拖动的数据与目标状态，并区分电脑文件拖入；文件页复用批量移动接口完成目录映射更新。同名检查和整组移动事务封装在后端 `files/service.py`，不调用存储服务。

`shares` 和 `share_sessions`，保存分享标题、加密令牌、密码哈希、有效期及访客授权。私有文件与分享公开读取通过不同入口鉴权，共用 `files/delivery.py`；媒体组件 `MediaViewer` 同时用于私人预览和分享页。
