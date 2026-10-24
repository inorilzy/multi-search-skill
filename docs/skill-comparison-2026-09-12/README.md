# 三个审查 skill 的实际比较

**结论：针对当前仓库“修好一处、下一轮再发现同类问题”的协作痛点，优先使用 `variant-analysis`。接口或契约变更时使用 `spec-to-code-compliance`；接手陌生模块或重构前使用 `audit-context-building`。三者是不同阶段的方法，不能用 bug 数直接排名。**

本轮均审查 `eb2d5cdeb222b52060c4509c45a22aff4ce911fa`，没有修复业务代码。未跟踪的旧第三轮报告保留。三个 skill 已安装到用户技能目录；配套引用文件、模板和原版代理/工作流源码均已保存，36 个文件通过存在性和 hash 清单检查。下一轮消息可自动发现，本轮直接读取已安装文件执行。

## 安装结果

来源：[Trail of Bits skills](https://github.com/trailofbits/skills/tree/321ccfe628eca0d314b0ee4eaffcdd8a05639aaf)，固定版本 `321ccfe628eca0d314b0ee4eaffcdd8a05639aaf`。

- [audit-context-building](C:/Users/zhiyu_liu/.codex/skills/audit-context-building/SKILL.md)
- [spec-to-code-compliance](C:/Users/zhiyu_liu/.codex/skills/spec-to-code-compliance/SKILL.md)
- [variant-analysis](C:/Users/zhiyu_liu/.codex/skills/variant-analysis/SKILL.md)

[installation.json](installation.json) 记录安装路径、每个文件 hash、相对资源引用检查及 60 个生产 Python 文件的基线 hash。没有安装运行外部 MCP 服务或修改项目依赖。

**运行方式边界：当前 Codex 没有这套插件要求的 `Workflow` 工具。** 本轮用独立子代理执行已安装 skill 的方法，之后检查结构化记录及独立复核。原版逐函数/逐需求自动扇出、模型返回 schema 强制和 slash workflow 并未运行；补齐源码不代表该运行时已可用。原版 plugin-root 资源路径在本次平铺 skill 安装中需要映射到对应 skill 的 resources 目录。

## 实际产出比较

| Skill | 本轮实际覆盖与结果 | 最适合你何时使用 | 成本与限制 |
|---|---|---|---|
| [variant-analysis](variant-analysis/REPORT.md) | 2 个已知根因作为种子；检查全部 12 个 MCP 工具，归并 7 个同步状态入口为同一阻塞问题族；13 组错误场景与 11 组 MCP 调用复跑。2 个 adapter 的条件性变体保留待验证 | 每次修 bug 后，马上检查全仓同类实现；特别适合多个 provider/多个公共入口 | 必须先有根因；原种子和历史已知问题不算首次发现；未知 provider 协议不能靠合成响应确认 |
| [spec-to-code-compliance](spec-compliance/REPORT.md) | 本轮登记 45 项规范单元，检查其中 25 项：24 项在各自限定范围内 implemented，1 项文档语义 undecidable；另有1项术语遗漏；11组离线探针通过 | 公共接口、输出格式、缓存契约和取消语义变更后，或发布前核对明确承诺 | 20项明确未查；文档没写的缺陷不在其天然发现范围；“共享逻辑通过”不等于全部adapter端到端通过 |
| [audit-context-building](audit-context/DOSSIER.md) | 60文件AST清单，读取31文件的相关区段，深查10函数，形成18条有证据不变量、8个开放问题 | 陌生模块、重大重构、跨模块状态/数据所有权不清时 | 它刻意不输出bug等级或修复；建立档案和追调用较重，不适合每次小改都全量重跑 |

实际记录的分析窗口约为：context 10分钟（未计早期技能阅读），spec 12分39秒，variant 10分钟（含主代理接手）。三者并行，计时起点并不相同，且范围不同；这些是执行记录，不能当速度排行榜。没有测得可比的 token/金额成本。

## 主代理复核后的发现与边界

1. **P2，已知问题族重现：同步状态 MCP 入口阻塞事件循环。** [server.py:109](D:/0-code-project/multi-search-skill/multi_search_mcp/server.py:109)、[server.py:169](D:/0-code-project/multi-search-skill/multi_search_mcp/server.py:169)、[server.py:181](D:/0-code-project/multi-search-skill/multi_search_mcp/server.py:181) 及四个状态管理入口共7个工具，在合法且触达状态的路径上等待SQLite写锁。持锁0.30秒使25ms定时回调延迟至约0.3秒。三种无状态/输入校验对照保持及时返回。这是第三轮已有问题的系统盘点，没有把6个种子外入口包装成6个新bug。
2. **条件性候选：Jina/Firecrawl的目标warning丢失来源。** [jina.py:152](D:/0-code-project/multi-search-skill/multi_search_mcp/src/scrape/scrapers/jina.py:152) 与 [firecrawl.py:42](D:/0-code-project/multi-search-skill/multi_search_mcp/src/scrape/scrapers/firecrawl.py:42) 的本地合成响应可导致错误key健康记账。已核对上游资料，但未取得“空正文+该warning”的完整真实触发样本；不计新增确定缺陷。具体证据和反例在变体报告中。
3. **P3，文档歧义：** [README.md:217](D:/0-code-project/multi-search-skill/README.md:217) 混合了Jina配置的静态exhausted和SQLite可恢复quota_exhausted。主代理和独立文档复核均确认：HTTP402路径并不写配置软删除，不能报成“永久禁用有效key”的代码bug。
4. **P3，术语遗漏：** [glossary.md:82](D:/0-code-project/multi-search-skill/docs/glossary.md:82) 没有列出真实存在的transient_invalid。应补齐现有状态表；它是文档完整性问题，不是业务阻塞。

“通过”项也做了检查：RRF中间不裁剪、缓存失效后原ID重抓、运行中任务取消保留容量由主代理复跑。特别保留REQ-23的范围限制：它只证实**已经显式标记target的结果**进入共享抓取逻辑后不会改key状态；没有验证所有adapter都正确产生该标记。报告里的24项implemented不能解释为24项保证在全系统所有分支均成立。

context档案的主要价值是把搜索/正文两个预算、取消与后台状态副作用、source_id/正文hash/URL scope三种身份、key选择/使用/结果记账三个时点分开。它为后续验证提供具体检查对象，本身不证明代码无错。

## 验证、执行异常与完整性

- 安装检查：`.venv/Scripts/python.exe -B .scratch/skill-comparison-20260912/validate_installation.py`。
- 变体探针：`.venv/Scripts/python.exe -B -X utf8 .scratch/skill-comparison-20260912/variants/probe.py`，主代理纠正GitHub探针的token传参后复跑，种子及对照断言通过。首版被安全guard截获的结果不作为证据。
- 规范探针：`.venv/Scripts/python.exe -B -X utf8 .scratch/skill-comparison-20260912/spec/offline_probe.py`，主代理复跑11组全部PASS。
- 最终记录校验与生产文件hash比对见 [verification.json](verification.json)。源码未变，不重复跑此前576项全套测试；本次也未声称远程、真实provider或生产验收通过。
- 变体子代理生成探针后被平台内容检查中止，主代理接手完成。另一次轻量验证代理因模型不受当前账户支持而未执行；后续由可用的默认代理完成文档反证。
- 文档反证代理首个广域搜索意外看到了审查报告片段，随后用当前源码/规范定向验证；其结论不能标作完全盲审。context/spec的主分析未读取历史审查，variant仅提前获得两个种子；主代理原本已知第三轮结果。本轮是一次实用方法试审，不是严格受控的技能优劣实验。

所有notChecked、开放问题、条件性候选和方法适配都保留。日常最小用法是：在修复票验收中加入variant全仓同类扫描；接口变更再加相关spec条目；架构档案仅在相应调用链变更时更新。不要因为安装了这三个skill，就把三份有界报告叫作“一次查全”。
