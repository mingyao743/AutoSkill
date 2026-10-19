# AutoSkill4Pi

让 [Pi Coding Agent](https://pi.dev/) 在使用中自主学会新技能。

**极简架构**：纯文件系统，零 Python，零 tool，零 bridge。Agent 直接读写 SKILL.md。

## 架构

```
<REPO>/AutoSkill4Pi/skills/    ← 元技能（创建/进化/捕获的指引）
├── create-skill/
│   └── SKILL.md               ← "如何创建技能"（融入 superpowers best practice）
├── evolve-skill/
│   └── SKILL.md               ← "如何进化技能"（darwin 9 维评估）
└── capturing-insights/
    └── SKILL.md               ← "如何捕获洞察"（闪记 → 技能的中间层）

~/.pi/agent/
├── skills/                    ← 用户技能（agent 学到的成熟技能）
│   ├── code-review-checklist/
│   │   └── SKILL.md           ← agent 用 Pi 原生 file tool 读写
│   └── formal-report-style/
│       └── SKILL.md
└── insights/                  ← 洞察闪记（原始观察，待提炼为技能）
    ├── 2026-10-19-json-trailing-commas.md
    └── 2026-10-19-api-rate-limit.md

Pi extension (autoskill-pi.ts, ~120 行):
  before_agent_start →
    1. 读 <REPO>/AutoSkill4Pi/skills/*/SKILL.md（元技能，全文注入）
    2. 读 ~/.pi/agent/skills/*/SKILL.md（用户技能，摘要注入）
    3. 读 ~/.pi/agent/insights/*.md（洞察闪记，标题列表注入）
    4. 拼入 system prompt

Agent:
  捕获洞察 → 按 capturing-insights 指引 → write insights/*.md
  创建技能 → 按 creating-skills 指引 → write skills/*/SKILL.md
  合并洞察 → 3+ 条同类 insight → 提炼为 skill
  更新技能 → edit SKILL.md, bump version
  进化技能 → 按 evolving-skills 指引 → 读 darwin 9 维 → 改写 SKILL.md
```

**知识沉淀分层：**
- **L1 原料层**：Pi 会话 JSONL（原始对话记录）
- **L2 半成品层**：`insights/`（闪记/洞察，原始观察）
- **L3 成品层**：`skills/`（用户技能，可复用制品）
- **L4 认知内核层**：元技能（创建/进化/捕获的方法论）

**没有后台 pipeline，没有 Python 子进程，没有 OpenAI 兼容桥。**
Extension 只做一件事：每次 agent 回复前，告诉它"你有哪些技能 + 有哪些洞察 + 如何创建/进化/捕获"。

## 安装

```bash
# 1. 复制 extension 到 Pi（子目录入口必须命名为 index.ts）
mkdir -p ~/.pi/agent/extensions/autoskill
cp AutoSkill4Pi/extension/autoskill-pi.ts ~/.pi/agent/extensions/autoskill/index.ts
cp AutoSkill4Pi/extension/package.json ~/.pi/agent/extensions/autoskill/

# 2. 创建技能和洞察目录
mkdir -p ~/.pi/agent/skills
mkdir -p ~/.pi/agent/insights
```

环境变量：

```bash
export AUTOSKILL_PI_REPO_DIR=/path/to/AutoSkill   # 必填：定位元技能目录
export AUTOSKILL_PI_SKILLS_DIR=~/.pi/agent/skills  # 可选：用户技能目录
```

## 工作原理

### 1. 会话开始

Extension 的 `before_agent_start` 读取两类 SKILL.md，注入 system prompt：

```
### Skill Learning (AutoSkill)

**Your current skills:**
- code-review-checklist (v0.2.0): Use when reviewing pull requests
- formal-report-style (v0.1.0): Use when writing reports in Chinese

**Skill creation & evolution guidance:**

--- creating-skills SKILL.md (full content) ---
--- evolving-skills SKILL.md (full content) ---
```

元技能（creating-skills、evolving-skills）的全文注入，让 agent 知道：
- **何时创建**：用户纠正、建立规则、表达偏好
- **如何命名**：name 永远英文 kebab-case，推荐 -ing 形式
- **description 陷阱**：只写触发条件，不总结 workflow（否则 agent 走捷径跳过正文）
- **如何进化**：darwin 9 维评估（目标清晰度、约束完整性、工作流合理性……）

### 2. Agent 创建技能

用户说："以后写代码注释都用中文"

Agent 按 creating-skills 指引，用 Pi 的 file write tool 创建：

```
~/.pi/agent/skills/chinese-code-comments/SKILL.md
```

内容：

```markdown
---
name: chinese-code-comments
description: 写代码注释时使用中文
version: 0.1.0
triggers: [写注释, 代码注释, code comments]
tags: [代码, 中文, 注释]
---
# Goal
所有代码注释使用中文。
# Constraints & Style
- 注释必须用中文
- 简洁明了
- 解释 why，不解释 what
```

### 3. 后续会话

Extension 注入时包含新技能 → agent 自动知道并遵循。

### 4. 进化

Agent 发现某技能经常被纠正 → 按 evolving-skills 指引的 9 维度评估 → 改写 SKILL.md。

## SKILL.md 格式

```markdown
---
name: english-kebab-case-name
description: Use when [specific triggering conditions and symptoms]
version: 0.1.0
triggers: [intent phrase 1, intent phrase 2, intent phrase 3]
tags: [keyword1, keyword2]
---

# Goal
What this skill achieves. Output contract only.

# Constraints & Style
Must-do and must-not-do rules.

# Workflow (optional)
Only for explicit multi-step AI operations.
```

**命名规范**：
- `name`：永远英文 kebab-case，推荐 -ing 形式（如 `creating-skills` > `skill-creation`）
- `description`：只写触发条件（"Use when..."），**不总结 workflow**
- `triggers` / `tags`：跟随用户语言，覆盖同义词和症状词

**description 陷阱**（来自 superpowers writing-skills）：
如果 description 总结了 workflow，agent 会走捷径直接按 description 做，跳过 SKILL.md 正文。
所以 description 只描述"什么时候用"，不描述"做什么"。

## 元技能（Meta-Skills）

元技能是项目自带的"关于技能"的技能，存放在 `<REPO>/AutoSkill4Pi/skills/`：

| 元技能 | 作用 |
|--------|------|
| `creating-skills` | 何时创建、SKILL.md 格式、命名规范、description 陷阱、从洞察合并为技能 |
| `evolving-skills` | darwin 9 维评估、进化时机、版本升级规则、常见进化模式 |
| `capturing-insights` | 何时捕获洞察、insight 格式、insight → skill 合并流程 |

修改元技能不需要改 TypeScript 代码，直接编辑对应的 SKILL.md 即可。

## 与 AutoSkill 主项目的关系

**零代码依赖。** Extension 只读文件系统，不 import autoskill，不 spawn Python。

AutoSkill 主项目（Python）作为可选离线工具箱独立存在：
- 离线批处理大量会话
- 高级语义检索（BM25 + vector）
- 复杂进化 Pipeline

唯一联系：SKILL.md 格式约定。

## 目录

```
AutoSkill4Pi/
├── extension/
│   ├── autoskill-pi.ts        # ~120 行，读元技能 + 用户技能 + 洞察 → 注入 prompt
│   └── package.json
├── skills/                    # 元技能（创建/进化/捕获的指引）
│   ├── create-skill/SKILL.md  # creating-skills
│   ├── evolve-skill/SKILL.md  # evolving-skills（含 darwin 9 维）
│   └── capturing-insights/SKILL.md  # capturing-insights
├── runtime/                   # 可选离线工具箱（extension 不调用）
│   ├── pi_session_adapter.py
│   ├── pi_skill_mirror.py
│   └── pi_runtime.py
└── README.zh-CN.md
```

## 对比旧架构

| | 旧架构 | 极简架构 |
|---|---|---|
| Extension 代码量 | ~300 行 | ~100 行 |
| 依赖 | Python + bridge + SkillBank | 文件系统 |
| Tool 数量 | 4 个 | 0 个 |
| Python 子进程 | 每次 tool 调用 | 无 |
| 技能指引 | 硬编码在 TS 里 | 元技能 SKILL.md（可编辑） |
| 技能存储 | SkillBank + mirror | 直接写 ~/.pi/agent/skills/ |
| 去重/版本 | Python maintainer | Agent 自己判断 |
| 搜索 | Python BM25 + vector | Agent grep / Pi 原生加载 |
