# Multi Search 0.4.1 桌面版

提供 macOS Apple Silicon、Windows x64 和 Linux x86_64 的桌面管理应用及内置 multi-search CLI。

## 下载与安装

- macOS：下载 `.dmg`，将 Multi Search 拖入 Applications。使用 ad-hoc 签名，未经过 Apple 公证。
- Windows：下载 NSIS `.exe` 安装程序，按当前用户安装。本次未配置代码签名证书，安装包未签名。
- Linux：提供 `.deb` 和 `.AppImage`。AppImage 需要执行权限及系统所需的 FUSE 支持。
- 各平台附带 `SHA256SUMS-<platform>.txt`，可核对安装包完整性。

应用内置锁定的 Python 运行时和 CLI 依赖，支持配置搜索源、凭据、Skill 和本机 CLI 安装。Linux 托管 CLI 位于绝对路径 `$XDG_DATA_HOME/MultiSearch/cli`，否则使用 `~/.local/share/MultiSearch/cli`；桌面可以发现并运行它，但自动注册 shell PATH 暂不支持。

## 本次打包修复

- Linux 不再打包 CLI 不使用的 terminfo 数据库，避免其大小写冲突文件名被资源清单拒绝；保留原有路径安全校验。
- Windows 无证书时不生成签名钩子；有证书时直接调用签名脚本，避免 NSIS 将内联 Python 的引号解析为额外参数。
- 补齐发布文档索引，并修正 Windows Cookie 测试中混合路径分隔符的预期。

## 验证与限制

发布流程校验锁定归档及依赖，构建后执行内置 CLI 版本检查；macOS 校验应用资源清单及签名，Linux 执行真实 bundle 安装、更新、卸载和篡改拒绝验收。最终可下载平台以实际附件为准。

私有依赖 xkit-py 当前被禁用，Twitter/X 可能返回缺少依赖的明确错误。发布前本机 Python 3.14.9 测试曾在两个 Twitter scraper 方法中出现 4 处失败断言；本版未修改相关逻辑。CI 中缺少该可选依赖时对应测试会跳过，不能据此判断此问题已修复。

安装包构建成功不表示所有外部服务、原生窗口交互和跨版本升级场景均已验收。macOS 未公证、Windows 未签名，系统可能显示来源或信誉提示。
