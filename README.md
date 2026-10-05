# WorkBuddy 手搓版（From-Scratch AI Assistant）

一个从零手搓的 WorkBuddy 式 AI 助手：包含**前端（流式对话 + Artifact 预览 + 专家/智囊团面板）**、**后端（FastAPI + LLM 编排）**、**Agent 编排引擎**、**智囊团 / 专家团 Swarm 多智能体协作**、**工具调用**与**记忆系统**。

> 目标不是复刻 WorkBuddy 的全部功能，而是把核心架构（编排 + Swarm + 工具 + Artifact）用最小可运行的代码手搓出来，并保留清晰的扩展点。

---

## 一、调研结论（怎么手搓一个 WorkBuddy）

### 1.1 多智能体编排的主流范式
参考 LangGraph / AutoGen / CrewAI / OpenAI Swarm 等框架，工程上可落地的编排模式有三类：

| 模式 | 特征 | 适用 | 失败点 |
|---|---|---|---|
| **集中式 Orchestrator-Worker** | 一个协调者持有任务计划，派发子任务给 Worker，可串行或并行 | 绝大多数场景，**先从这个开始** | 协调者是单点瓶颈 |
| **去中心化 Mesh** | 无中心，Agent 通过消息总线直接通信、自分配任务 | 实时、高吞吐 | 行为难预测、级联失败 |
| **分层 Multi-Tier** | Planner → 中层协调 → Worker，类似 VP→经理→员工 | 10+ 种 Agent 的企业级 | 协调开销随层级叠加 |

**结论**：本实现采用「集中式 Orchestrator-Worker」为主线，并在其上叠加 **Swarm（扇出/扇入）** 与 **分层规划** 两种变体，覆盖单 Agent、专家团、复杂任务分解三类需求。

### 1.2 智能体间通信原语
- **共享黑板（Blackboard）**：所有 Agent 读写同一个状态对象。实现简单、易观测，集中式架构首选。
- **直接消息传递**：结构化 JSON 载荷，每次交接必须做 schema 校验，防止幻觉级联。
- **事件发布/订阅**：适合事件驱动、实时场景。

本实现的「会话上下文 + 事件流」本质是 **Blackboard + 事件流** 的混合：编排器维护全局上下文（黑板），并通过 SSE 事件流把每一步推给前端（观测）。

### 1.3 共识 / 仲裁策略（Swarm 的灵魂）
当多个专家并行产出结果后，需要合并：
- **多数投票（Majority Voting）**：AutoGen 辩论模式用 Aggregator 做多数表决。
- **置信度加权投票（Confidence-Weighted）**：ReConcile 框架让每个 Agent 给出置信度，按置信度倒数（不确定度）加权汇总。
- **信任值路由**：按历史表现动态调整权重。

本实现的 Swarm 采用 **「并行专家产出 + 置信度加权 + 综合者（Synthesizer）二次综合」**，即每个专家附带 confidence，综合者据此组织最终答案。

### 1.4 前端流式方案
- **SSE（Server-Sent Events）** 是 LLM 流式 UX 的最佳选择：单向、自动重连、标准 HTTP、比 WebSocket 简单。
- 密钥必须留在**服务端代理**，浏览器不持有任何密钥。
- 事件应结构化（token / tool_call / artifact / done），前端按事件类型渲染对话、工具调用链、Artifact 预览。
- 引入 Markdown 渲染与代码高亮提升可读性。

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                          前端 (SPA, 原生JS)                     │
│  ┌──────────┐   ┌────────────────────┐   ┌──────────────────┐ │
│  │ 侧边栏    │   │   对话区(流式)       │   │ Artifact/活动面板 │ │
│  │ 模式/专家 │   │   SSE token 渲染     │   │ 代码/HTML 预览    │ │
│  └──────────┘   └────────────────────┘   └──────────────────┘ │
└───────────────────────────┬──────────────────────────────────┘
                            │  POST /api/chat (SSE)
┌───────────────────────────┴──────────────────────────────────┐
│                      后端 (FastAPI)                            │
│                                                                │
│  ┌────────────┐   ┌────────────────────────────────────────┐  │
│  │  路由层     │   │           编排引擎 (Orchestrator)        │  │
│  │ /api/chat  │──▶│  1) Router 决策 (agent|swarm|plan)      │  │
│  │ /api/agents│   │  2) 单 Agent 推理循环 (带工具)           │  │
│  │ /api/reset │   │  3) Swarm 扇出/扇入 + 置信加权综合       │  │
│  └────────────┘   └───────────────┬────────────────────────┘  │
│                                    │                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ Agent 注册 │  │  LLM 层   │  │  工具系统 │  │   记忆系统    │   │
│  │ 专家/通用  │  │ OpenAI兼容│  │ search/  │  │ 会话上下文    │   │
│  │           │  │ + Mock   │  │ code/file│  │ 持久化 JSON   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 目录结构
```
.
├── README.md                 # 本文：调研 + 架构 + 运行
├── config.env.example        # 环境变量模板
├── backend/
│   ├── requirements.txt
│   ├── run.py                # 启动入口
│   └── app/
│       ├── config.py         # 配置（LLM 端点/密钥/模型）
│       ├── schemas.py        # 数据模型
│       ├── llm.py            # LLM 客户端（OpenAI 兼容 + Mock 流式）
│       ├── memory.py         # 会话记忆（内存 + JSON 持久化）
│       ├── tools/            # 工具：web_search / code_exec / file_ops
│       ├── agents/           # Agent 基类 / 注册表 / 专家定义
│       ├── orchestrator.py   # 路由 + 单 Agent 推理循环
│       ├── swarm.py          # 智囊团：并行专家 + 置信加权综合
│       └── main.py           # FastAPI 路由 + 静态托管
└── frontend/
    ├── index.html            # SPA 骨架
    ├── styles.css            # 样式
    └── app.js                # SSE 消费 + 渲染 + 交互
```

---

## 三、核心引擎设计

### 3.1 LLM 层（`llm.py`）
- 统一异步生成器接口：`stream_chat(messages, tools)` 产出 `{type:"token"}` / `{type:"tool_calls"}` / `{type:"done"}`。
- **真实路径**：OpenAI 兼容 `/v1/chat/completions`，`stream:true`，原生 `tools` 函数调用。
- **Mock 路径**：无密钥也能跑通全链路（编排、Swarm、工具、前端），按 Agent 角色生成拟真回复，可演示工具调用。
- 通过 `MOCK_MODE=auto|true|false` 切换。

### 3.2 Agent 层（`agents/`）
- `Agent` 基类：`tag / name / role / system_prompt / tools / color`。
- 注册表：`register()` / `get()` / `list()`。
- 内置专家：
  - **通用助手 general**（无工具，兜底）
  - **研究员 researcher**（web_search, file_ops）
  - **工程师 coder**（code_exec, file_ops）
  - **评审 critic**（分析、挑刺）
  - **规划者 planner**（任务分解）

### 3.3 编排器（`orchestrator.py`）
- **Router 算法**：根据查询复杂度与关键词，决定 `agent`（单专家）/ `swarm`（智囊团）/ `plan`（分层分解）。Mock 用启发式，真实用 LLM 结构化输出。
- **单 Agent 推理循环（ReAct 风格）**：
  1. 带系统提示 + 工具定义调用 LLM；
  2. 若返回 `tool_calls` → 执行工具（发 `tool_call`/`tool_result` 事件）→ 把结果回填上下文 → 回到 1（最多 N 轮）；
  3. 否则流式输出最终答案，并扫描答案中的代码块 → 作为 **Artifact** 事件推给前端。

### 3.4 智囊团 Swarm（`swarm.py`）—— 重点
- **扇出（fan-out）**：把同一问题并发派发给 N 个专家（`asyncio.gather` 并行）。
- 每个专家产出 `{answer, confidence∈[0,1]}`。
- **扇入（fan-in）**：综合者（Synthesizer）按 **置信度加权** 组织最终答案——高置信专家的意见优先，并显式标注分歧与共识。
- 前端把每位专家的观点作为「投票/观点」卡片实时展示。

### 3.5 工具系统（`tools/`）
- 统一接口：`name / description / parameters(JSON Schema) / async run(**kwargs)`。
- `web_search`：模拟/可接真实搜索，返回结构化片段。
- `code_exec`：在沙箱目录里用托管 Python 子进程执行代码（带超时与基础危险调用拦截），返回 stdout/stderr。
- `file_ops`：在沙箱目录内读/写/列文件。

### 3.6 记忆系统（`memory.py`）
- 每会话一个消息列表（Blackboard），同时落盘 `data/sessions.json`，重启可恢复。
- 预留长期记忆 / 摘要压缩扩展点。

---

## 四、运行方式

### 4.1 安装依赖（使用托管 Python 的隔离 venv）
```bash
PY="C:/Users/22521/.workbuddy/binaries/python/versions/3.13.12/python.exe"
$PY -m venv "C:/Users/22521/.workbuddy/binaries/python/envs/default"
# Windows 下 venv 的可执行文件在 Scripts 目录：
" C:/Users/22521/.workbuddy/binaries/python/envs/default/Scripts/pip.exe" install -r backend/requirements.txt
```

### 4.2 配置（可选，接入真实模型）
```bash
cp config.env.example config.env
# 编辑 config.env：
#   OPENAI_API_KEY=sk-xxx
#   OPENAI_BASE_URL=https://api.openai.com/v1   # 或本地 Ollama: http://localhost:11434/v1
#   MODEL=gpt-4o-mini
#   MOCK_MODE=auto        # 有密钥走真实，无密钥走 Mock
```
不配置也能跑：默认 `MOCK_MODE=auto`，无密钥时自动进入 Mock，全链路可演示。

### 4.3 启动
```bash
"C:/Users/22521/.workbuddy/binaries/python/envs/default/bin/python" backend/run.py
# 浏览器打开 http://localhost:8000
```

### 4.4 体验路径
1. 普通提问 → 走单 Agent 流式回答。
2. 打开「智囊团」开关 → 多专家并行 + 置信加权综合。
3. 让工程师写一段 HTML/Python → 右侧出现 Artifact 实时预览。
4. 让研究员「搜索 …」→ 触发 web_search 工具调用链可见。

---

## 五、后续扩展路线（算法 / 编排增强）
- **分层规划 Plan 模式**：Planner 分解 → 多 Worker 并行 → Reviewer 校验（已预留路由分支）。
- **真实 RAG**：替换 web_search 为向量检索 + 重排。
- **信任值路由**：基于历史成功率动态调整专家权重。
- **Human-in-the-loop**：关键动作（发邮件/执行）前暂停等待确认。
- **可观测**：Trace ID + Mermaid 执行图，对接 LangSmith 式面板。
- **Mesh 模式**：去中心化消息总线，水平扩展。
