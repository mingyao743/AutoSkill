# AutoSkill4Pi

让 [Pi Coding Agent](https://pi.dev/) 在使用中自主学会新技能。

AutoSkill4Pi 是 [AutoSkill](../README.zh-CN.md)（经验驱动终身学习 ELL）到 Pi 的集成。
Agent 自己决定何时抽取技能、何时更新技能——不需要后台 pipeline，不需要 OpenAI 兼容桥。

## 核心架构

```
Pi 进程
  └─ extension: autoskill-pi.ts
       ├─ before_agent_start → 注入技能摘要 + 抽取引导到 system prompt
       ├─ autoskill_create   → agent 主动创建技能（写入 SkillBank + mirror）
       ├─ autoskill_update   → agent 主动更新技能（版本递增）
       ├─ autoskill_list     → agent 查看技能列表
       └─ autoskill_search   → agent 按关键词检索技能
                                  │
                                  ▼
        AutoSkill4Pi/runtime (Python, 纯存储层)
          ├─ SkillBank CRUD      技能增删改查 + 版本管理
          ├─ pi_skill_mirror     SkillBank → ~/.pi/agent/skills（带托管标记）
          └─ pi_session_adapter  Pi JSONL → 轨迹记录（兼容离线批处理）
```

**设计原则**：
- **Agent 是抽取引擎**：agent 有完整对话上下文，比后台 pipeline 更懂"该抽什么"；
- **SkillBank 是真源**：`~/.pi/agent/skills` 只是镜像，非真源；
- **镜像安全**：只覆盖 AutoSkill 创建的目录（`.autoskill-managed.json` 标记），同名人工技能用 `<slug>-autoskill` 后缀并存，绝不覆盖；
- **无桥架构**：不再需要 OpenAI 兼容 bridge，agent 自己就是 LLM。

## 工作流程

```
1. 会话开始
   before_agent_start → agent 看到当前技能列表 + 抽取引导

2. 会话进行中
   agent 发现用户纠正/建立规则 → 调用 autoskill_create
   → Python 写入 SkillBank → 自动 mirror 到 ~/.pi/agent/skills

3. 后续会话
   agent 通过 before_agent_start 看到新技能 → 直接复用

4. 技能不好用？
   agent 调用 autoskill_update → 版本递增（v0.1.0 → v0.1.1）
```

## 安装

前置：Python 3.10+、已 `pip install -e .` 安装 autoskill、已安装可运行的 Pi。

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
export AUTOSKILL_PI_REPO_DIR=/abs/path/to/AutoSkill
export AUTOSKILL_PI_PYTHON=python3
```

## Agent 工具

### autoskill_create

创建新技能。当用户纠正你的做法、建立可复用规则、或表达明确偏好时调用。

参数：
- `name`（必填）：英文 kebab-case，如 `code-review-checklist`
- `description`（必填）：1-2 句话说明做什么、何时用
- `prompt`（必填）：技能 prompt，包含 `# Goal` + `# Constraints & Style`
- `triggers`：3-5 个触发意图短语
- `tags`：1-6 个关键词

### autoskill_update

更新已有技能。当技能不好用或用户再次纠正了技能覆盖的场景时调用。

参数：
- `skill_id`（必填）：要更新的技能 ID
- `name` / `description` / `prompt` / `triggers` / `tags`：可选更新字段

### autoskill_list

列出所有技能，返回 ID、名称、版本、描述。

### autoskill_search

按关键词检索技能。开始任务前检查是否有相关技能。

参数：
- `query`（必填）：检索关键词

## System Prompt 注入

`before_agent_start` 会自动注入以下内容到 system prompt：

```
### Skill Learning (AutoSkill)

You have the ability to learn and reuse skills across sessions.

**When to create a skill (call autoskill_create):**
- User corrects your approach ("no, it should be...", "wrong, change to...")
- User establishes a reusable rule ("from now on, always...")
- User expresses a clear preference ("don't use...", "prefer...")

**Skill naming rules:**
- name: ALWAYS English kebab-case
- description/prompt/triggers/tags: match user's language

**Your current skills:**
- code-review-checklist (v0.2.0): Checklist for reviewing code changes
- formal-report-style (v0.1.0): Write formal reports in Chinese
```

Agent 据此知道：有哪些技能、何时创建新技能、命名规范。

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTOSKILL_PI_REPO_DIR` | （必填） | AutoSkill 仓库根（含 `AutoSkill4Pi/`） |
| `AUTOSKILL_PI_PYTHON` | `python3` | 运行时解释器 |
| `AUTOSKILL_PI_USER_ID` | `pi` | 技能归属的 user_id |
| `AUTOSKILL_PI_STORE_DIR` | `~/.pi/autoskill/SkillBank` | 技能真源目录 |
| `AUTOSKILL_PI_SKILLS_DIR` | `~/.pi/agent/skills` | 用户级技能镜像目录 |

## CLI（Python 侧）

```bash
# 列出所有技能
python3 -m AutoSkill4Pi.runtime.pi_runtime list-skills --format json
python3 -m AutoSkill4Pi.runtime.pi_runtime list-skills --format text

# 创建技能（agent tool 内部调用）
python3 -m AutoSkill4Pi.runtime.pi_runtime create-skill --payload '{"name":"...","description":"...","prompt":"..."}'

# 更新技能
python3 -m AutoSkill4Pi.runtime.pi_runtime update-skill --payload '{"skill_id":"...","description":"..."}'

# 检索技能
python3 -m AutoSkill4Pi.runtime.pi_runtime search --query "发布说明"

# 重新镜像
python3 -m AutoSkill4Pi.runtime.pi_runtime mirror

# 离线批处理（兼容旧流程）
python3 -m AutoSkill4Pi.runtime.pi_runtime process-dir --dir ~/.pi/agent/sessions
```

## 与旧架构的区别

| | 旧架构 | 新架构 |
|---|---|---|
| 抽取决策 | 后台 Python pipeline | Agent 自主决定 |
| LLM 调用 | Bridge → Pi 模型 | Agent 自己就是 LLM |
| 触发时机 | `agent_settled`（会话结束后） | `before_agent_start`（会话进行中） |
| 技能延迟 | 下次会话才生效 | 当场创建，下轮可用 |
| 上下文 | Python 只看文本 | Agent 有完整推理链 |
| 复杂度 | TS + bridge + Python | TS + Python（纯存储） |

## 目录

```
AutoSkill4Pi/
├── extension/
│   ├── autoskill-pi.ts        # Pi extension: context hook + skill tools
│   └── package.json
├── runtime/
│   ├── pi_session_adapter.py  # Pi JSONL → 轨迹记录（离线批处理用）
│   ├── pi_skill_mirror.py     # SkillBank → ~/.pi/agent/skills 镜像
│   └── pi_runtime.py          # SkillBank CRUD + CLI
├── install.py
└── README.zh-CN.md
```

## Darwin-skill 进化

`autoskill/evolution/SKILL.md` 提供了基于 darwin-skill 的 9 维度技能优化能力。
Agent 可以在创建技能后手动触发进化，或通过 `/autoskill_evolve` 命令检查需要进化的技能。

进化是可选的增强步骤——创建技能本身已经是高质量抽取（agent 有完整上下文）。
