# 04: 交付紧凑 search_web 与 Source Registry

**What to build:** 新增候选优先的 `search_web` Core 与 MCP 入口，让一次搜索只完成选源、并发召回、标准化、保守 URL 去重和紧凑输出，并为每次响应及候选建立可供后续正文读取使用的短期标识；现有重型入口保持兼容。

**Blocked by:** 01: 恢复 Route 对抓取默认值的控制; 02: 统一内容语义与 Provider Capability.

**Status:** resolved

- [x] `search_web` 支持 Route 或显式 Sources、数量、超时和查询扩展等候选搜索参数。
- [x] 每次响应包含 `response_id`，每个规范化候选包含在该响应内稳定且唯一的 `source_id`。
- [x] 紧凑 SearchHit 至少包含标题、原始 URL、canonical URL、受限长度的 content、来源、发布时间、正文可用性和内容引用信息。
- [x] canonicalization 只规范大小写、默认端口、fragment、已知跟踪参数和查询顺序；保留未知业务参数且不强制合并 HTTP/HTTPS。
- [x] 同一响应中的同一 canonical URL 只生成一个候选，并保留所有命中 Provider 的来源信息。
- [x] Source Registry 能在短期生命周期内把 `source_id` 解析回候选元数据，但不把正文塞入搜索响应。
- [x] `search_web` 在任何 Provider 返回形态下都不会调用抓取后端，也不会返回 `body`、`full_content` 或 `scraped_content` 大文本。
- [x] Provider 部分失败时仍返回成功候选，并在 diagnostics 中明确失败来源。
- [x] MCP 入口只是 Core 的薄包装；测试通过假的 Provider 验证完整行为，不访问真实网络或用户密钥。
- [x] 旧 `multi_search` 和 `scrape_url` 的参数及主要返回字段没有被删除或重命名。

## Answer

已在 `f6bb21e` 完成：交付候选优先 `search_web`、紧凑 SearchHit、`response_id/source_id`、Source Registry、保守 URL canonicalization 和兼容 MCP 薄入口。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
