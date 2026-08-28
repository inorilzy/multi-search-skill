# 06: 交付扩展查询两级 RRF 与失败诊断

**What to build:** 当 `search_web` 扩展一个查询为多个角度时，先分别融合每个查询下的 Provider 排名，再融合不同查询的结果，使 Provider 共识和查询角度共识各自只计算一次，并让部分失败对调用方可见。

**Blocked by:** 05: 交付单查询确定性 RRF.

**Status:** resolved

- [x] 每个扩展查询先独立执行 Provider 级 RRF，再以其融合结果参与查询级 RRF。
- [x] 实现不会把所有 Provider 与查询列表直接平铺成一次投票。
- [x] 相同 URL 在不同查询角度出现时能获得查询级共识提升，同时保持同一层内的去重规则。
- [x] Provider 失败和查询角度失败分别记录在 diagnostics 中，部分成功不会被呈现为完整覆盖。
- [x] 改变 Provider 或扩展查询的完成顺序不会改变最终结果。
- [x] 单查询模式仍保持 Ticket 05 的既有输出和排序语义。
- [x] 测试覆盖完整成功、Provider 部分失败、查询角度部分失败和全部失败边界。

## Answer

已在 `f6bb21e` 与 `d6e9732` 完成：expanded query 采用两级 RRF，并分别输出 `provider_failures` 与无有效候选角度的 `query_failures`，覆盖角度部分失败和全部失败。

验证：Python 3.11、3.12、3.14 下全量 261 项测试通过；CLI/MCP smoke、compileall、pip check 与 Standards/Spec 两轴审查通过。
