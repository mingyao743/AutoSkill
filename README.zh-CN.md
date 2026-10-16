# AutoSkill: 经验驱动的终身学习

[English](README.md) | 中文

<p align="center">
  <a href="https://github.com/ECNU-ICALK/AutoSkill"><img src="https://img.shields.io/badge/Maintained%20By-ICALK-0A66C2" alt="Maintained By ICALK" /></a>
  <a href="https://arxiv.org/abs/2603.01145"><img src="https://img.shields.io/badge/arXiv-2603.01145-b31b1b.svg" alt="arXiv 2603.01145" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License MIT" /></a>
</p>

AutoSkill 将 Agent 交互经验转化为可复用、自进化的技能。

## 工作原理

```
人类 ←→ Agent ←→ 技能 ←→ 组织资产
  ↑                              ↓
  └──────────────────────────────┘
```

1. **提取** — 从 Agent 交互中蒸馏出 `SKILL.md` 文件
2. **存储** — 技能在 SkillBank 中积累为组织资产
3. **加载** — 技能镜像到 Agent 工作区，Agent 原生加载
4. **进化** — 基于 darwin-skill 的 9 维评估 + 配对比较，技能自我优化

## 架构

```
用户对话 / Agent 轨迹
        ↓
    提取 (LLM)
        ↓
   SkillBank (SKILL.md + 向量)
        ↓
    镜像 → Agent 工作区
        ↓
  Agent 原生加载技能
        ↓
  Provenance 累积 → 触发进化
        ↓
  Darwin-skill 循环：评估 → 变异 → 保留/回滚 → 回写
```

## 模块

| 模块 | 用途 |
|---|---|
| [`autoskill/`](autoskill/README.md) | 核心 SDK：提取、维护、存储、代理 |
| [`AutoSkill4Pi/`](AutoSkill4Pi/README.zh-CN.md) | Pi Coding Agent 集成 |
| [`AutoSkill4OpenClaw/`](AutoSkill4OpenClaw/README.md) | OpenClaw 集成 |
| [`AutoSkill4Doc/`](AutoSkill4Doc/README.md) | 文档转技能管道 |
| [`autoskill/evolution/`](autoskill/evolution/SKILL.md) | 基于 darwin-skill 的自进化 |

## 快速开始

```bash
# 安装
pip install -e .

# 交互式聊天
python3 -m examples.interactive_chat

# OpenAI 兼容代理
python3 -m examples.openai_proxy

# 从已有对话提取
python3 -m autoskill.offline.conversation.extract --input conversations.json
```

## 仓库结构

```
autoskill/          核心 SDK
AutoSkill4Pi/       Pi Agent 集成
AutoSkill4OpenClaw/ OpenClaw 集成
AutoSkill4Doc/      文档提取
SkillBank/          本地技能存储
examples/           可运行示例
tests/              测试
```

## 引用

```bibtex
@misc{yang2026autoskill,
  title={AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution},
  author={Yutao Yang et al.},
  year={2026},
  eprint={2603.01145},
  archivePrefix={arXiv},
  primaryClass={cs.AI}
}
```

## 许可证

MIT
