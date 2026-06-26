# multi-search 路由重设计 · 实施方案

> 状态：已实施 / 已验证
> 适用代码：`multi_search_mcp/src/*`（canonical runtime）
> 关联文档：`docs/route-capability-table.md`（能力表）

实施结果：本方案已落地到 canonical runtime。旧 `scripts/*` 不作为主运行路径处理。

验证命令：

```powershell
python -m pytest test_mcp_architecture.py -q
python -m pytest -q
python -m compileall multi_search_mcp/src
```

本方案综合 GPT 的三层心智模型、GLM 的落地层补强（`ROUTE_META` + 降级策略），并按"别过度工程"原则做了两处修正（不自动生成单 provider route、lite/fast 二选一）。

---

## 0. 当前真实现状（已对代码核对，勿凭记忆）

`ROUTE_PROFILES`（`search_runner.py`）实际内容：

```python
"default":     {brave, tavily, exa, firecrawl, serpapi, github_repos, twitter}
"lite":        {tavily, exa}
"discussion":  {twitter}          # 注意：当前只有 twitter，不是多源
"video":       {youtube, bilibili}
# 其余 22 条全是单 provider route / alias
```

关键代码事实（决定本方案能否落地）：

| 事实 | 位置 | 影响 |
|---|---|---|
| `scrape_top` 是全局单值（默认 30），只有 `route=="video"` 特判强制 0 | service.py | per-route 抓取必须改 service |
| answer 展示靠全局 `verbose`（`show_answers = verbose and not brief`） | format.py | per-route 展示必须改 formatter |
| `sources` 参数直接 bypass route | service.py:103 | 单 provider 可走 sources，无需 route |
| keyed provider 走 SQLite 轮换 | registry.py | brave exa firecrawl linuxdo reddit serpapi tavily v2ex youtube |
| 非 keyed provider（cookie/token/本地，无轮换、易失效） | registry.py | deepseek_web glm_web twitter reddit_oauth linuxdo_api zhihu hackernews github_repos bilibili stackoverflow |

> 结论：route 改名/增删只是 dict 改动，但"快速模式少抓+显示 answer / 专家模式多抓+显示正文"**必须改 `service.py` 和 `format.py`**，不是加个 dict 就完。

---

## 1. 目标

1. 收窄默认行为，去掉 `default` 里的平台源污染（twitter/github）。
2. 用三层心智模型替代当前 26 条平铺 route。
3. 让 route 真正承载行为差异（抓取量、展示方式、超时、结果数），而不只是 provider 集合。
4. 处理非 keyed provider 不可用时的降级，避免"名为 fast 实跑 lite"的名实不符。
5. 总 route 数下降，单 provider 改走 `sources`，减少维护面。

---

## 2. 三层路由模型

### Layer 1 · 通用 Web（事实搜索，默认稳）

| route | provider 集合 | 说明 |
|---|---|---|
| `web`（= `default` 别名） | brave, tavily, exa, serpapi | 纯事实搜索，去掉 firecrawl/twitter/github |
| `fast` | deepseek_web, glm_web, tavily, exa | answer 优先：直接拿模型总结，少 scrape |
| `expert` | brave, tavily, exa, serpapi, firecrawl | 多源 + firecrawl，深抓正文 |

> `lite` 删除，并入 `fast`（二选一，修正 GLM 保留 lite 的不自洽）。
> `news` 不单列；时效需求让 `fast`/`web` 在查询里加时间词。

### Layer 2 · 专用平台（站点搜索，不进默认）

这些不是"通用 vs 快速/专家"的横向区分，而是按站点纵向分类。统一不进 `web/fast/expert`，按需通过 route 名或 `sources` 调用。

| route | provider | 认证类型 |
|---|---|---|
| `social` | twitter, reddit_oauth | 非 keyed（twscrape / token） |
| `dev` | stackoverflow, github_repos, hackernews | 非 keyed |
| `cn-community` | zhihu, v2ex, linuxdo | 混合（部分 keyed） |
| `video` | youtube, bilibili | youtube keyed |

### Layer 3 · 单 provider —— 不进 ROUTE_PROFILES

删除全部 22 条单 provider route / alias。需要指定单源时走 `sources` 参数（代码已支持 bypass）。这是**删代码**，不是 GLM 提的"自动生成"（那是加间接层）。

```
# 旧：route="brave"
# 新：sources=["brave"]
```

保留历史别名（`linux-do`→`linuxdo` 等）可选，建议直接删。

---

## 3. ROUTE_META（GLM 核心贡献，必须新增）

`ROUTE_PROFILES` 只管 provider 集合；新增 `ROUTE_META` 管行为：

```python
ROUTE_META = {
    "web":    {"scrape_top": 8,  "show_answer": True,  "show_snippet": True,  "count": 8,  "timeout": 60},
    "fast":   {"scrape_top": 0,  "show_answer": True,  "show_snippet": True,  "count": 5,  "timeout": 30},
    "expert": {"scrape_top": 20, "show_answer": False, "show_snippet": True,  "count": 12, "timeout": 90},
    "social": {"scrape_top": 0,  "show_answer": False, "show_snippet": True,  "count": 8,  "timeout": 45},
    "dev":    {"scrape_top": 5,  "show_answer": False, "show_snippet": True,  "count": 8,  "timeout": 60},
    "cn-community": {"scrape_top": 5, "show_answer": False, "show_snippet": True, "count": 8, "timeout": 60},
    "video":  {"scrape_top": 0,  "show_answer": False, "show_snippet": False, "count": 10, "timeout": 45},
}
DEFAULT_META = {"scrape_top": 30, "show_answer": False, "show_snippet": True, "count": 10, "timeout": 60}
```

设计要点：
- `fast.scrape_top = 0` —— 快速模式不抓正文，直接用 deepseek/glm 的 answer（呼应"直接总结=快速模式"）。
- `expert.show_answer = False` —— 专家模式给 scrape 正文，不靠模型总结。
- 请求里显式传的 `scrape_top/verbose/brief` 仍可覆盖 route 默认（保持现有覆盖语义）。

---

## 4. 非 keyed provider 降级策略（GLM，必须定义）

问题：`fast` 依赖 `deepseek_web/glm_web`，`social` 依赖 `twitter/reddit_oauth`，这些非 keyed、易失效。若全不可用，`fast` 会静默退化成 `tavily+exa`（= 旧 lite），用户看到 "fast" 却跑了 lite。

规则：
1. 每个含非 keyed provider 的 route 标注 `degrade_to`（keyed-only 兜底集合）。
   - `fast.degrade_to = {tavily, exa}`
   - `social.degrade_to = {}`（专用平台无 web 兜底，直接报"平台源不可用"）
2. 运行时若 route 内"有效 provider 数为 0"，按 `degrade_to` 兜底，并在结果里**显式标注降级**（不静默）。
3. formatter 在降级时输出一行提示，例如：
   `> ⚠️ fast 降级：deepseek/glm 不可用，已回退至 tavily+exa`

---

## 5. 改动清单（按文件）

### search_runner.py
- 重写 `ROUTE_PROFILES` 为 Layer 1+2（7 条），删除 22 条单 provider route。
- 新增 `ROUTE_META` / `DEFAULT_META` / 各 route 的 `degrade_to`。
- `resolve_route`：保留；`lite=True` 改为映射到 `fast`（兼容旧 --lite）。

### service.py
- `scrape_top` 解析顺序改为：请求显式值 > config > **ROUTE_META[route]** > DEFAULT_META。
- `count` / `timeout` 同理引入 route 默认。
- 去掉 `route=="video"` 硬编码特判（改由 `ROUTE_META["video"]["scrape_top"]=0` 表达）。
- 计算"有效 provider 数"，为 0 时按 `degrade_to` 兜底并设 `degraded=True` 传入 formatter。

### format.py
- `format_results` 增参 `show_answer` / `show_snippet`（来自 ROUTE_META），替代当前 `show_answers = verbose and not brief` 的全局逻辑（保留 verbose 作为强制开关）。
- 接受 `degraded` 标记，输出降级提示行。

### SKILL.md
- route 引导改为三层模型；删除单 provider route 的触发说明，改引导用 `sources`。
- 明确 fast=快速总结 / expert=深抓正文 / web=默认事实搜索。

### docs/route-capability-table.md
- 同步新 route 命名与能力对应。

---

## 6. 删除 / 合并 / 重命名汇总

| 动作 | 对象 | 原因 |
|---|---|---|
| 重命名 | `default` → `web`（`default` 保留为别名指向 `web`） | 去污染、语义清晰 |
| 删除 | `lite` | 并入 `fast` |
| 删除 | 22 条单 provider route/alias | 改走 `sources` |
| 新建 | `social` `dev` `cn-community` | Layer 2 平台分类 |
| 改写 | `discussion`（当前仅 twitter） | 并入 `social` |
| 保留 | `video` | 已是合理多源 route |

route 总数：26 → 7（web/fast/expert/social/dev/cn-community/video）。

---

## 7. 测试补强

1. `resolve_route` 单测：7 条 route 各自的 provider 集合。
2. ROUTE_META 解析优先级单测：请求值 > config > route meta > default。
3. 降级单测：mock 非 keyed provider 全失败 → 验证 `fast` 回退 `{tavily,exa}` 且 `degraded=True`。
4. formatter 单测：`show_answer=True` 时展示 deepseek/glm answer；降级时输出提示行。
5. `sources` bypass 回归：传 `sources=["brave"]` 行为等价旧 `route="brave"`。

---

## 8. 迁移与兼容

- `default` 行为变化（去掉 twitter/github）：保留 `default` 别名指向 `web`，但**行为 break**，需在 changelog 标注。
- 旧脚本传 `route="brave"` 等单 provider route 会失效：提供别名兼容期（可选），或直接 break 并在 SKILL/文档说明改用 `sources`。
- `--lite` flag 映射到 `fast`，不破坏旧调用。

---

## 9. 分阶段落地

1. **P1（低风险，纯 dict）**：重写 ROUTE_PROFILES + 新增 ROUTE_META，service.py 接 route 默认值，去掉 video 特判。
2. **P2（formatter）**：format.py 接 show_answer/show_snippet，修复 answer 默认被藏的 bug。
3. **P3（降级）**：有效 provider 数判断 + degrade_to + 降级提示。
4. **P4（清理）**：删单 provider route、更新 SKILL.md 与能力表、补测试。

每阶段可独立合入、独立验证。
