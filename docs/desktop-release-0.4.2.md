# Multi Search 0.4.2 桌面版

提供 macOS Apple Silicon、Windows x64 和 Linux x86_64 的桌面管理应用及内置 multi-search CLI。

## 下载与安装

- macOS：下载 `.dmg`，将 Multi Search 拖入 Applications。使用 ad-hoc 签名，未经过 Apple 公证。
- Windows：下载 NSIS `.exe` 安装程序，按当前用户安装。本次未配置代码签名证书，安装包未签名。
- Linux：提供 `.deb` 和 `.AppImage`。AppImage 需要执行权限及系统所需的 FUSE 支持。
- 各平台附带 `SHA256SUMS-<platform>.txt`，可核对安装包完整性。

## 主要变化

- 服务商账号：Key 按账号分组管理，账号来自浏览器登录（Firecrawl、Parallel 设备码登录，Brave、Exa 复用 Chrome 登录）或粘贴的独立 Key。
- 用量与余额：新增用量页和 `balance` / 用量命令，按账号显示额度、余额和消耗速度，并在本机记录搜索与抓取调用统计。
- 搜索过程可视化：测试搜索实时显示路由、各搜索器耗时、融合与模型重排对比；可选开启搜索详情日志，并在本机日志页查看。
- 结果质量：近似重复 URL 合并、同一网站结果条数上限；SerpApi 返回的 Google 跳转链接会尽量还原为真实地址，未能还原的保留原链接；AI 答案不再作为独立搜索源列出。
- 抓取：Jina / Firecrawl 拆分为带 Key 与匿名两条通道，每个抓取后端单次调用有超时上限（默认 10 秒）。
- 性能：打开服务商弹窗时，Key 来源状态从内存读取并在后台刷新；调用 CLI 前不再每次检查版本；托管 CLI 的完整性校验改为文件指纹比对加定期全量校验。

## 验证与限制

CI 在 Linux、macOS、Windows 上运行 Python 3.10 / 3.14 测试、桌面 Rust 与前端测试。发布流程校验锁定归档及依赖，构建后执行内置 CLI 版本检查。

私有依赖 xkit-py 当前被禁用，Twitter/X 可能返回缺少依赖的明确错误；CI 中依赖私有仓库的 Twitter 测试任务需要有效的 `XKIT_READ_TOKEN` 才能运行。

SerpApi 部分 Google 跳转链接需要较长等待才能解析，为不拖慢搜索，这部分链接保留原样，可能无法与其他来源的同一页面合并。

安装包构建成功不表示所有外部服务、原生窗口交互和跨版本升级场景均已验收。macOS 未公证、Windows 未签名，系统可能显示来源或信誉提示。
