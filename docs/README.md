# TG Pan 私人网盘

以 Telegram 私有频道存储文件，以 PostgreSQL 维护目录与文件块映射。面向个人使用及 1 核 1GB 内存的 VPS；前后端分开开发，生产环境由 FastAPI 同时提供 API 和前端构建产物。

- [技术栈和工程结构](architecture.md)
- [本地运行、VPS 部署和备份](deployment.md)
- [验证情况与真实联调边界](validation.md)
- [安全机制、验证及部署边界](security-audit.md)
- [帐号与权限](features/accounts.md)
- [文件系统与回收站](features/files.md)
- [上传下载与恢复](features/transfers.md)
- [离线下载与 aria2 管理](features/offline.md)
- [视频下载、Cookie 与元数据](features/videos.md)
- [图片与视频预览](features/preview.md)
- [文件与目录分享](features/shares.md)
- [Telegram 配置](features/telegram.md)
- [中英文国际化](features/i18n.md)

支持 HTTP/HTTPS、磁力和 BT 种子离线下载，以及视频网站单视频、分 P 和播放列表下载，自动转存 Telegram。视频可选择画质或仅提取音频，支持 Cookie 管理与元数据查询；管理员可在网页安装和更新 aria2、yt-dlp、ffmpeg。支持管理员创建帐号、独立文件空间、多组机器人配置、目录管理、文件与文件夹上传、下载、移动/重命名、批量操作、搜索排序和回收站。单个逻辑文件最大 5,000,000,000 字节（5GB），通过多个 Telegram 附件存储。支持图片与视频预览，视频可拖动进度条。支持带密码、有效期和自定义标题的文件与目录分享，分享页可逐层浏览目录、下载文件、查看图片和播放视频。目录打包下载暂未实现。

不自动导入直接发送到频道的文件。请勿手动删除存储频道里的文件块；目录和映射需要数据库才能恢复，不能仅靠频道还原原文件系统。
