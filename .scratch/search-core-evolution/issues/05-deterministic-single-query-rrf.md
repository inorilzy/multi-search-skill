# 05: 交付单查询确定性 RRF

**What to build:** 让 `search_web` 对单个查询的多 Provider 候选采用等权 RRF 融合，保留每个 Provider 的原始排名和诊断分数，使结果由跨源共识决定，而不是由响应先后、正文长度或不同 Provider 的不可比原生分数决定。

**Blocked by:** 04: 交付紧凑 search_web 与 Source Registry.

**Status:** resolved

- [x] 每个 Provider 返回后立即保留其内部原始 rank，原生 score 只作为诊断数据。
- [x] 使用等权 RRF，初始 rank constant 为 40，rank window 为 15。
- [x] 改变 Provider 完成顺序不会改变最终候选顺序或 RRF 分数。
- [x] 多个 Provider 命中的同一 canonical URL 能获得跨源共识提升。
- [x] 同一 Provider 内的重复 URL 只贡献一次排名票。
- [x] 同一 Provider 使用多把 key 失败切换后仍只产生一份 Provider 排名列表，不因 key 数量增加权重。
- [x] 正文是否存在、正文长度和 Provider 原生 score 不参与跨 Provider 的直接排序比较。
- [x] SearchHit 输出稳定的 Provider ranks 与 RRF score，并受既定数量和响应大小限制。

## Answer

已在 `f6bb21e` 完成：单查询采用等权 RRF（`k=40`、窗口 15），保留 Provider rank，去除完成顺序、正文长度和不可比原生 score 对融合排序的影响。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
