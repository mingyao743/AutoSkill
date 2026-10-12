# AutoSkill4Pi

让 [Pi Coding Agent](https://pi.dev/) 在不改核心、不替换 system prompt 的前提下，随使用持续学会新技能。

AutoSkill4Pi 是 [AutoSkill](../README.zh-CN.md)（经验驱动终身学习 ELL）到 Pi 的集成，沿用
`AutoSkill4OpenClaw` 已验证的 **adapter + SkillBank 真源 + 原生 skills 镜像** 模式：

- 每个会话收口后，自动从完整 Pi 会话轨迹里抽取可复用技能；
- 发现更好做法时，自动合并/更新旧技能并递增版本（v0.1.0 → v0.1.1）；
- 把当前有效技能镜像到 Pi **用户级** `~/.pi/agent/skills/`，由 Pi 原生渐进式技能加载机制去发现与使用；
- 抽取所用 LLM **复用 Pi 当前模型**（通过 extension 内置的本地 OpenAI 兼容 bridge），无需另配一套模型/key。

## 运行形态：Extension adapter（形态 A）

```
Pi 进程
  └─ extension: autoskill-pi.ts
       ├─ session_start      → 启动本地模型 bridge（OpenAI 兼容 /v1/chat/completions）
       ├─ agent_settled      → 后台拉起 Python runtime：扫描 Pi 会话目录做抽取/维护
       ├─ /autoskill_extract_now、/autoskill_sync 命令
       └─ autoskill_search 工具（模型可主动检索技能库，只读）
                                  │
                                  ▼
        AutoSkill4Pi/runtime (Python, provider=generic → bridge)
          ├─ pi_session_adapter  Pi JSONL → 轨迹记录（活跃分支/工具事件/成败）
          ├─ 离线轨迹抽取        add/merge/discard + 版本演进 → SkillBank 真源
          └─ pi_skill_mirror     SkillBank → ~/.pi/agent/skills（带托管标记）
```

设计原则（与 OpenClaw 集成一致）：
- SkillBank 是技能**真源**；`~/.pi/agent/skills` 只是安装镜像，非真源；
- 镜像只覆盖 AutoSkill 自己创建的目录（`.autoskill-managed.json` 标记）；同名的人工技能改用 `<slug>-autoskill` 后缀并存，**绝不覆盖**；
- 检索注入默认交给 Pi 原生技能机制，不做第二层重复检索；
- 防递归：AutoSkill 注入的 `custom_message`（`customType` 以 `autoskill` 开头）在转换时被过滤，不会被再次抽取。

## Pi 会话格式（对接依据）

来源：Pi 官方文档 `docs/sessions.md` 与 `docs/session-format.md`。

- 存储：`~/.pi/agent/sessions/--<cwd 转义>--/<时间戳>_<session-id>.jsonl`
- 结构：JSONL，条目用 `id`/`parentId` 构成**树**；模型只看 leaf→root 的**活跃分支**
- 关键条目：`session`(header) / `message`(user|assistant|toolResult|system) / `compaction` / `branch_summary` / `custom_message` / `usage` / `model_change` 等
- 转换器规则：user 回合为主证据；assistant 文本 + toolCall/toolResult 组成轨迹事件；system/usage/label 等元数据跳过；终态为报错 toolResult 判为不成功

## 安装

前置：Python 3.10+（本仓库以 3.9 也能跑通核心）、已 `pip install -e .` 安装 autoskill、已安装可运行的 Pi。

```bash
cd /path/to/AutoSkill
python3 -m pip install -e .
python3 AutoSkill4Pi/install.py --repo-dir "$(pwd)"
```

安装器会：
- 把 extension 复制到 `~/.pi/agent/extensions/autoskill/`
- 创建 `~/.pi/autoskill/SkillBank` 与 `~/.pi/agent/skills`

启动 Pi 前设置环境变量：

```bash
export AUTOSKILL_PI_REPO_DIR=/abs/path/to/AutoSkill   # 含 AutoSkill4Pi/ 的仓库根
export AUTOSKILL_PI_PYTHON=python3                     # 安装了 autoskill 的解释器
```

然后正常使用 `pi`。会话收口后会自动触发抽取；也可随时 `/autoskill_extract_now` 主动触发、`/autoskill_sync` 重新镜像。

### 验证技能已产出并被 Pi 使用

```bash
find ~/.pi/autoskill/SkillBank/Users -name SKILL.md | head
find ~/.pi/agent/skills -name SKILL.md | head
```

在 Pi 里对相关任务，Pi 会按 `description` 自动加载命中的技能；也可 `/skill:<name>` 强制加载。

## 复用 Pi 当前模型（bridge）

extension 在 `session_start` 时在本进程起一个仅监听 `127.0.0.1` 的 OpenAI 兼容
`POST /v1/chat/completions` 服务，内部转调 Pi 的模型运行时（`ctx.modelRegistry.streamSimple`）。
Python 侧以 `provider=generic` 指向该 bridge，从而**复用 Pi 正在用的模型与鉴权**，无需为抽取另配 provider/key。

⚠️ **接入真实 Pi 后需核对的唯一一点**：`extension/autoskill-pi.ts` 里 `callPiModel()`
对 `ctx.modelRegistry.streamSimple(...)` 的入参/返回签名。若你的 Pi 版本形态不同，只需改这一个函数。
其余逻辑（`session_start`/`agent_settled`/`session_shutdown` 事件、`registerCommand`、`registerTool`、spawn python）均按官方 `docs/extensions.md` 契约实现。

备选（不想用 bridge）：直接设 `AUTOSKILL_PI_LLM_BASE_URL=<任意 OpenAI 兼容端点>` 与
`AUTOSKILL_PI_LLM_MODEL` / `AUTOSKILL_PI_LLM_API_KEY`，config-resolve 回退即可，无需改代码。
embeddings 默认走本地 `hashing`（不联网、无需 key）；如需更强检索可设 `AUTOSKILL_PI_EMBEDDINGS_PROVIDER`。

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTOSKILL_PI_REPO_DIR` | （必填） | AutoSkill 仓库根（含 `AutoSkill4Pi/`） |
| `AUTOSKILL_PI_PYTHON` | `python3` | 抽取运行时使用的解释器 |
| `AUTOSKILL_PI_USER_ID` | `pi` | 技能归属的 user_id |
| `AUTOSKILL_PI_STORE_DIR` | `~/.pi/autoskill/SkillBank` | 技能真源目录 |
| `AUTOSKILL_PI_SKILLS_DIR` | `~/.pi/agent/skills` | 用户级技能镜像目录 |
| `AUTOSKILL_PI_LEDGER` | `~/.pi/autoskill/processed_ledger.jsonl` | 幂等去重账本 |
| `AUTOSKILL_PI_SESSIONS_DIR` | `~/.pi/agent/sessions` | Pi 会话根目录 |
| `AUTOSKILL_PI_LLM_PROVIDER` | `generic` | `generic`(bridge) / `mock` / `dashscope` 等 |
| `AUTOSKILL_PI_LLM_BASE_URL` | bridge 注入 | generic 端点（config-resolve 时手填） |
| `AUTOSKILL_PI_LLM_MODEL` / `_API_KEY` | bridge 注入 | 同上 |
| `AUTOSKILL_PI_EMBEDDINGS_PROVIDER` | `hashing` | `hashing`/`none`/`openai`/`generic`/`dashscope`/`glm` |
| `AUTOSKILL_PI_LIVE_EXTRACT_EVERY_TURNS` | `0`(关) | >0 时活跃会话每 N turn 做一次 checkpoint 抽取 |
| `AUTOSKILL_PI_BM25_WEIGHT` | `0.7` | 检索里 BM25 权重（离线场景偏 BM25） |
| `AUTOSKILL_PI_INCLUDE_TOOL_EVENTS` | `1` | 轨迹事件是否并入抽取 |
| `AUTOSKILL_PI_SUCCESS_ONLY` | `0` | 仅对成功会话抽取 |

## CLI（Python 侧，可独立使用/离线批处理）

```bash
# 处理单个会话文件
python3 -m AutoSkill4Pi.runtime.pi_runtime process --session <file.jsonl>
# 扫描整个会话目录（账本幂等，自动补处理历史漏掉的会话；--dir 支持 ~ 前缀，
#   未显式传 --dir 时回退读 AUTOSKILL_PI_SESSIONS_DIR，再回退 ~/.pi/agent/sessions）
python3 -m AutoSkill4Pi.runtime.pi_runtime process-dir --dir ~/.pi/agent/sessions
# 重新镜像 SkillBank → 用户级 skills
python3 -m AutoSkill4Pi.runtime.pi_runtime mirror
# 检索技能（供 autoskill_search 工具）
python3 -m AutoSkill4Pi.runtime.pi_runtime search --query "发布说明 指标"
```

## 测试

Python 侧核心（会话适配、抽取结构保真、镜像、账本去重、防递归、成败推断）已用 mock provider 端到端跑通：

```bash
python3 AutoSkill4Pi/tests/test_pipeline.py   # 10/10 通过
```

- `tests/fixtures/sample_session.jsonl`：含分支/系统消息/AutoSkill 注入/工具事件的合成会话
- 覆盖：活跃分支重建、abandoned 分支排除、autoskill 流量过滤、tool_call/tool_result 事件、终态报错判失败、分支指纹去重、镜像写 Pi 兼容 SKILL.md、陈旧技能清理、不覆盖同名人工技能
- 回归覆盖：多条结构化轨迹逐条抽取不被压平（`success_only`/`include_tool_events` 真实生效）、重复镜像就地更新不产生 `-2` 副本并清理历史重复目录、`--dir` 对 `~` 前缀正确展开

## 目录

```
AutoSkill4Pi/
├── extension/
│   ├── autoskill-pi.ts        # Pi 扩展：事件钩子 + 模型 bridge + 拉起 Python（形态 A）
│   └── package.json
├── runtime/
│   ├── pi_session_adapter.py  # Pi 会话 JSONL → AutoSkill 轨迹记录
│   ├── pi_skill_mirror.py     # SkillBank → 用户级 skills 镜像（托管标记/防覆盖/清理）
│   └── pi_runtime.py          # 编排：配置/账本/抽取/镜像 + CLI
├── tests/
│   ├── fixtures/sample_session.jsonl
│   └── test_pipeline.py
├── install.py
└── README.zh-CN.md
```

## 待你在真实 Pi 上完成的收尾

1. 核对并按需微调 `callPiModel()` 的 `streamSimple` 调用签名（复用 Pi 模型）；
2. 首次 `agent_settled` 后确认 `~/.pi/agent/skills/` 出现带 `.autoskill-managed.json` 的技能目录；
3. Pi 里用 `/skill:<name>` 验证命中与加载；观察 `/autoskill_extract_now` 的输出与账本去重。
