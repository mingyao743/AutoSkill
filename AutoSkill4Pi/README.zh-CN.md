# AutoSkill4Pi

让 [Pi Coding Agent](https://pi.dev/) 在使用中自主学会新技能。

**极简架构**：纯文件系统，零 Python，零 tool，零 bridge。Agent 直接读写 SKILL.md。

## 架构

```
~/.pi/agent/skills/          ← 唯一的数据存储
├── code-review-checklist/
│   └── SKILL.md             ← agent 用 Pi 原生 file tool 读写
├── formal-report-style/
│   └── SKILL.md
└── darwin-skill/            ← 进化技能（元技能）
    └── SKILL.md

Pi extension (autoskill-pi.ts, ~80 行):
  before_agent_start → 读目录 → 注入技能摘要 + 引导到 system prompt

Agent:
  创建技能 → write SKILL.md
  更新技能 → edit SKILL.md
  进化技能 → 读 darwin-skill + 当前技能 → 改写 SKILL.md
```

**没有后台 pipeline，没有 Python 子进程，没有 OpenAI 兼容桥。**
Extension 只做一件事：每次 agent 回复前，告诉它"你有哪些技能，何时创建/更新/进化"。

## 安装

```bash
# 1. 复制 extension 到 Pi
mkdir -p ~/.pi/agent/extensions/autoskill
cp AutoSkill4Pi/extension/autoskill-pi.ts ~/.pi/agent/extensions/autoskill/
cp AutoSkill4Pi/extension/package.json ~/.pi/agent/extensions/autoskill/

# 2. 创建技能目录
mkdir -p ~/.pi/agent/skills
```

可选环境变量：

```bash
export AUTOSKILL_PI_SKILLS_DIR=~/.pi/agent/skills   # 默认值
```

## 工作原理

### 1. 会话开始

Extension 的 `before_agent_start` 读取 `~/.pi/agent/skills/*/SKILL.md`，注入 system prompt：

```
### Skill Learning (AutoSkill)

**Your current skills:**
- code-review-checklist (v0.2.0): Checklist for reviewing code changes
- formal-report-style (v0.1.0): Write formal reports in Chinese

**When to create a skill:**
- User corrects your approach
- User establishes a reusable rule
→ Create directory and write SKILL.md

**SKILL.md format:**
---
name: english-kebab-case-name
description: 1-2 sentences
version: 0.1.0
---
# Goal ...
# Constraints & Style ...
```

### 2. Agent 创建技能

用户说："以后写代码注释都用中文"

Agent 用 Pi 的 file write tool 创建：

```
~/.pi/agent/skills/chinese-code-comments/SKILL.md
```

内容：

```markdown
---
name: chinese-code-comments
description: 写中文代码注释
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

Agent 发现某技能经常被纠正 → 读 darwin-skill 的 9 维度评估 → 改写 SKILL.md。

## SKILL.md 格式

```markdown
---
name: english-kebab-case-name
description: 1-2 sentences, what this skill does and when to use it
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
- `name`：永远英文 kebab-case
- `description` / `prompt` / `triggers` / `tags`：跟随用户语言

## 与 AutoSkill 主项目的关系

**零代码依赖。** Extension 只读文件系统，不 import autoskill，不 spawn Python。

AutoSkill 主项目（Python）作为可选离线工具箱独立存在：
- 离线批处理大量会话
- 高级语义检索（BM25 + vector）
- 复杂进化 pipeline

唯一联系：SKILL.md 格式约定。

## 目录

```
AutoSkill4Pi/
├── extension/
│   ├── autoskill-pi.ts        # ~80 行，读目录 + 注入 prompt
│   └── package.json
├── runtime/                   # 可选离线工具箱（extension 不调用）
│   ├── pi_session_adapter.py
│   ├── pi_skill_mirror.py
│   └── pi_runtime.py
└── README.zh-CN.md
```

## 对比旧架构

| | 旧架构 | 极简架构 |
|---|---|---|
| Extension 代码量 | ~300 行 | ~80 行 |
| 依赖 | Python + bridge + SkillBank | 文件系统 |
| Tool 数量 | 4 个 | 0 个 |
| Python 子进程 | 每次 tool 调用 | 无 |
| 技能存储 | SkillBank + mirror | 直接写 ~/.pi/agent/skills/ |
| 去重/版本 | Python maintainer | Agent 自己判断 |
| 搜索 | Python BM25 + vector | Agent grep / Pi 原生加载 |
