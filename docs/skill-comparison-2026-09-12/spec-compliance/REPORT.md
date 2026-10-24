# Spec-to-code compliance：首轮比较报告

固定 HEAD：`eb2d5cdeb222b52060c4509c45a22aff4ce911fa`。开始 `2026-09-13T03:36:09+00:00`，完成 `2026-09-13T03:48:47.729149+00:00`。

本轮没有确认业务缺陷。选定25条需求：24 implemented、1 undecidable；另记录1条尚待独立核实的文档遗漏。共显式登记45条规范单元，20条未查。这个数字是本轮有界inventory，不是“全仓库所有规范共45条”。生产源码证据覆盖21个文件，11组离线探针通过。

## 发现及反证

1. **REQ-24 / Low / 文档歧义，unverified。** README.md:217 的“余额接口确认后才自动标exhausted”把两层状态放在一起。`jina.py:175-179,194-196`按HTTP402直接产生result.exhausted；`key_state.py:219-222`写24小时运行态quota_exhausted。纯离线探针确实只调用一次模拟Reader，未调用wallet。**但主代理提出并经本作者检查的反证成立：README上下文为配置对象的长期软删除，keys.py:90-98与mark_exhausted.py:32-52表明配置exhausted另有手动写入路径，HTTP分支没有写配置。** 因此不能声称“402永久禁用”或确认代码违约。建议把配置软删除、运行态自动冷却/配额恢复和旧wallet描述分开说明。最终独立结论由主代理记录。
2. **UD-01 / Low / 当前规范遗漏，unverified。** `key_state.py:18-25,198-214`有transient_invalid，首次invalid先冷却15分钟，累计3次才invalid；docs/glossary.md:82-86只列5种状态。离线实测首次invalid得到transient_invalid。文档搜索限定当前规范集合，无该状态/阈值说明。影响是运维解释状态困难，不是要求删掉恢复机制；未声称仓库所有历史文档都没写。

没有把大小写归一化的H1匹配、正常API fallback链、use_state=False返回不可跨调用读取的source_id、取消后线程仍运行当作缺陷：这些要么是明确边界，要么文档不足以支持指控。候选自身反证不是独立验证；本报告保留unverified状态供主代理处理。

## 规范选取与执行方法

权威顺序：用户指定的当前 README、CONTEXT 概念定义、glossary 单一术语来源、mcp-dispatch 专门调度契约、当前 Skill 及search/verification接口说明。不同文档的同义保证合并；复杂行只判本条标题明确的原子范围。路线图、provider历史免费额度、历史审查与修复记录均未作为硬需求，也未读取历史审查结论。本轮先阅读规范并在上下文列出样本，再追代码；磁盘inventory与报告在读完后写出，并未声称做过可验证时间戳的预注册。

已实际读取并使用安装的SKILL、ANALYSIS_FORMAT、DOMAIN_NOTES、DIVERGENCE_RUBRIC，补读checker agent与workflow的alignment schema及独立反证阶段。平铺安装的resources对应原资源引用中的`{baseDir}/skills/spec-to-code-compliance/resources`。环境没有Workflow工具，且4个并发槽服务于3个skill比较，因此这是**Codex适配执行**：一个子代理逐条记录、主代理独立复核差异；没有假称原版“每需求一个agent+两个独立反证agent+schema强制返回”已运行。`requirements/*.json`具备schema要求的requirementId/verdict/confidence/searched/reasoning/analysisFile和evidence；这里只做磁盘结构校验，不等于原Workflow模型返回schema约束。

## Alignment matrix

| ID | 原子检查范围 | Verdict | Confidence |
|---|---|---|---|
| [REQ-01](requirements/REQ-01.md) | MCP 与 CLI 搜索调用共享 Core | implemented | high |
| [REQ-02](requirements/REQ-02.md) | CLI 全失败、零匹配、部分成功退出语义 | implemented | high |
| [REQ-03](requirements/REQ-03.md) | 显式 sources 覆盖 route 选源 | implemented | high |
| [REQ-04](requirements/REQ-04.md) | disabled_sources 对显式源生效且全禁用明确失败 | implemented | high |
| [REQ-05](requirements/REQ-05.md) | 同 query/provider 重复 URL 仅按最佳名次投票 | implemented | high |
| [REQ-06](requirements/REQ-06.md) | 两级 RRF 无中间截断且最终最多15 | implemented | high |
| [REQ-07](requirements/REQ-07.md) | 候选摘要与正文各自保留 | implemented | high |
| [REQ-08](requirements/REQ-08.md) | 预取正文按长度/provider/文本确定性选择 | implemented | high |
| [REQ-09](requirements/REQ-09.md) | 有匹配H1时预览偏移指向原正文标题 | implemented | medium |
| [REQ-10](requirements/REQ-10.md) | 旧 scrape_top 不再裁剪最终抓取列表 | implemented | high |
| [REQ-11](requirements/REQ-11.md) | source_id 是一次响应内canonical URL的短期身份 | implemented | high |
| [REQ-12](requirements/REQ-12.md) | 有效 source_id 的缓存失效后仍以原ID重抓 | implemented | high |
| [REQ-13](requirements/REQ-13.md) | read_source 缓存未命中不会隐式联网 | implemented | high |
| [REQ-14](requirements/REQ-14.md) | full_content 覆盖max_chars并保留取得的全部正文 | implemented | high |
| [REQ-15](requirements/REQ-15.md) | 跨响应URL缓存复用不延长原TTL | implemented | high |
| [REQ-16](requirements/REQ-16.md) | 禁止正文持久化的provider策略优先 | implemented | high |
| [REQ-17](requirements/REQ-17.md) | use_state=false跳过SQLite及站点记忆 | implemented | high |
| [REQ-18](requirements/REQ-18.md) | 搜索timeout是整批共享deadline | implemented | medium |
| [REQ-19](requirements/REQ-19.md) | 正文超时保留排名结果及显式失败 | implemented | high |
| [REQ-20](requirements/REQ-20.md) | 四个耗时MCP入口共享4槽且满载立即拒绝 | implemented | high |
| [REQ-21](requirements/REQ-21.md) | MCP取消不能提前释放正在运行任务容量 | implemented | high |
| [REQ-22](requirements/REQ-22.md) | key选择优先未使用其次最久未用 | implemented | high |
| [REQ-23](requirements/REQ-23.md) | 目标页面错误不改key健康状态、不轮换key | implemented | high |
| [REQ-24](requirements/REQ-24.md) | Jina自动exhausted必须先由余额接口确认 | undecidable | high |
| [REQ-25](requirements/REQ-25.md) | fetch目标URL统一执行SSRF输入校验 | implemented | high |

## 验证与边界

运行：`.venv\Scripts\python.exe -B .scratch\skill-comparison-20260912\spec\offline_probe.py`。

11组离线探针覆盖：显式选源和禁用、RRF无中间截断、URL去重、预览/全文/跨ID缓存TTL/原ID重抓/read离线、key LRU/target中立/首invalid状态、Jina402语义、5种不安全URL、H1字符偏移、running cancel保留槽、fetch deadline部分成功、完整模拟搜索prefetch与state关闭、CLI退出1/0/0。组合场景合计组数以probe-results.json为准，组内断言没有冒充独立需求测试数量。

网络安全：拦截socket.getaddrinfo/connect/connect_ex、urllib urlopen/OpenerDirector.open及subprocess.run/Popen；Jina仅用内存HTTPError；StateStore只写自有`.scratch/.../spec/probe.sqlite`，service默认keys/config读取被设为立即失败。无真实API请求、无默认用户状态、无真实密钥或cookie读取。源码全部保持不变；没有运行全套正式测试或真实MCP ClientSession/ServerSession。测试通过只证明这些本地模拟，不证明生产网络质量或provider条款正确。

## 未查清单

- NC-01：密钥环境变量覆盖与所有凭据读取边界（README.md:L67）
- NC-02：行为配置路径优先级（docs/glossary.md:L97）
- NC-03：显式配置路径不存在时报错（README.md:L35）
- NC-04：read_source keyword/offset Unicode映射全部边界（docs/glossary.md:L74）
- NC-05：read_source单次8000字符上限（README.md:L345）
- NC-06：ContentStore容量与所有LRU淘汰并发路径（docs/glossary.md:L71）
- NC-07：所有禁用/冷却/配额恢复状态的生命周期（README.md:L270）
- NC-08：每个route精确成员、默认count/timeout与alias全集（README.md:L157）
- NC-09：所有provider缺key及Twitter依赖失败隔离（README.md:L179）
- NC-10：Reddit专用适配器及禁止进入通用后端（README.md:L107）
- NC-11：Reddit评论最多100条8层及不支持链接类别（README.md:L109）
- NC-12：Reddit代理变量与匿名token生命周期（README.md:L109）
- NC-13：V2EX全部API参数及忽略索引正文（README.md:L147）
- NC-14：Jina匿名优先/限流后使用key（README.md:L269）
- NC-15：全部scraper backend选择及站点记忆优先顺序（README.md:L269）
- NC-16：所有输出格式逐字段untrusted标记及Markdown清理（README.md:L285）
- NC-17：SourceRegistry每批事务清理与索引（docs/glossary.md:L72）
- NC-18：预览摘要逐字匹配阈值32及全部HTML/围栏边界（skills/multi-search/references/search.md:L62）
- NC-19：每个adapter的归一化空体与目标/provider分类（README.md:L366）
- NC-20：宿主Agent委派、保留不确定候选及全文引用流程（skills/multi-search/SKILL.md:L22）

unreadableDocuments为空。unverified为REQ-24、UD-01；没有把未查事项判成absent或用undecidable掩盖工作未完成。

## 此Skill的实际收益、成本、适用范围

收益：最有价值的不是新增bug数量，而是把“文档承诺是什么”变成可复核的输入，再检查共享入口、正文缓存及取消边界。Jina候选在区分两层状态后被降为文档问题，避免了危险的假阳性建议。逐条原文、源码范围、真实rg命中和notChecked清单使复核者能判断覆盖程度。

成本：25条规范的拆分/去重与逐条报告比普通通读审查重；同一个service.py被多次追踪。一个context承载所有路径比原版每需求隔离弱，JSON落盘只能增加透明度，不能替代原Workflow的schema约束及两个独立反证agent。本轮结果只能评价其检查方法在Codex适配下的作用，不能直接拿它与另外skill的bug数量排名。

适用：契约迁移、接口兼容、发布前核对文档保证；规范越明确收益越高。对文档未提及的新安全漏洞/性能根因不应作为唯一审计方法。建议主代理独立复核文档候选，并抽查已判implemented的REQ-06/REQ-12/REQ-21，避免只反证“发现”、不审证“通过”。
