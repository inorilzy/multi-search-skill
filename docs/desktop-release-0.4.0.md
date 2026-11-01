# Multi Search 0.4.0 桌面版

本版本提供桌面管理应用及内置的 multi-search CLI，用于配置搜索源、凭据、Skill 和本地 CLI 安装。发布构建由 `v0.4.0` tag 触发。

## 下载

- macOS Apple Silicon：`.dmg`，将 Multi Search 拖入 Applications。
- Windows x64：NSIS `.exe` 安装程序，按当前用户安装。
- Linux x86_64：`.deb` 和 `.AppImage`。Debian/Ubuntu 可安装 deb；AppImage 需执行权限及系统所需的 FUSE 支持。
- 每个平台附带 `SHA256SUMS-<platform>.txt`。

macOS 构建采用 ad-hoc 签名，未经过 Apple 公证。Windows 未配置代码签名证书时产出未签名安装包，系统可能显示来源或信誉提示。这里不声称已通过操作系统商店分发认证。

## 功能与安装

- 共享 Core 和按需 CLI，桌面应用管理本机搜索配置、凭据及 Skill。
- 内置锁定版本的 Python 运行时和依赖，用户不必另行配置 Python 才能运行内置 CLI。
- Linux 托管 CLI 使用绝对路径 `XDG_DATA_HOME` 下的 `MultiSearch/cli`；未设置时使用 `~/.local/share/MultiSearch/cli`。桌面应用可以发现并运行它，但 Linux 自动注册 shell PATH 暂不支持；从终端调用时需使用完整路径或自行配置 PATH。
- 此版本暂时禁用私有依赖 xkit-py；Twitter/X 功能可能返回缺少依赖的明确错误。

## 验证范围与已知问题

发布流程校验 Python 归档 SHA-256、锁定依赖和 Rust 工具链，构建后运行内置 CLI 检查版本，并校验 macOS 应用签名与资源清单。安装包构建成功不等同于所有桌面交互、外部搜索服务和升级路径均已验收。

发布前的 macOS Python 3.14.9 全套测试运行 1211 项，存在 Twitter scraper 两个测试方法中的 4 处失败断言，另有 10 项跳过；预算和调用次数差异已独立复现，尚未修复。其余已执行的 JavaScript 测试、类型检查、文档检查和 Rust 领域测试通过，但部分平台验收测试被跳过或忽略。

本次不声称真实外部服务、原生窗口完整交互、所有跨版本升级场景已验证。最终可下载平台以本 Release 实际附件为准。
