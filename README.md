# AutoSkill: Experience-Driven Lifelong Learning

English | [中文](README.zh-CN.md)

<p align="center">
  <a href="https://github.com/ECNU-ICALK/AutoSkill"><img src="https://img.shields.io/badge/Maintained%20By-ICALK-0A66C2" alt="Maintained By ICALK" /></a>
  <a href="https://arxiv.org/abs/2603.01145"><img src="https://img.shields.io/badge/arXiv-2603.01145-b31b1b.svg" alt="arXiv 2603.01145" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License MIT" /></a>
</p>

AutoSkill turns agent interactions into reusable, self-evolving skills.

## How It Works

```
Human ←→ Agent ←→ Skills ←→ Organ Assets
  ↑                              ↓
  └──────────────────────────────┘
```

1. **Extract** — Agent interactions are distilled into `SKILL.md` files
2. **Store** — Skills accumulate in SkillBank as organizational assets
3. **Load** — Skills are mirrored to agent workspace; agent loads them natively
4. **Evolve** — Skills self-improve via darwin-skill's 9-dimension rubric + paired evaluation

## Architecture

```
User Dialog / Agent Trajectory
        ↓
    Extract (LLM)
        ↓
   SkillBank (SKILL.md + vectors)
        ↓
    Mirror → Agent Workspace
        ↓
  Agent loads skills natively
        ↓
  Provenance accumulates → Trigger Evolution
        ↓
  Darwin-skill loop: evaluate → mutate → keep/revert → write back
```

## Components

| Module | Purpose |
|---|---|
| [`autoskill/`](autoskill/README.md) | Core SDK: extraction, maintenance, storage, proxy |
| [`AutoSkill4Pi/`](AutoSkill4Pi/README.zh-CN.md) | Pi Coding Agent integration |
| [`AutoSkill4OpenClaw/`](AutoSkill4OpenClaw/README.md) | OpenClaw integration |
| [`AutoSkill4Doc/`](AutoSkill4Doc/README.md) | Document-to-skill pipeline |
| [`autoskill/evolution/`](autoskill/evolution/SKILL.md) | Darwin-skill based self-evolution |

## Quick Start

```bash
# Install
pip install -e .

# Interactive chat
python3 -m examples.interactive_chat

# OpenAI-compatible proxy
python3 -m examples.openai_proxy

# Extract from existing conversations
python3 -m autoskill.offline.conversation.extract --input conversations.json
```

## Repository Structure

```
autoskill/          Core SDK
AutoSkill4Pi/       Pi Agent integration
AutoSkill4OpenClaw/ OpenClaw integration
AutoSkill4Doc/      Document extraction
SkillBank/          Local skill storage
examples/           Runnable demos
tests/              Tests
```

## Citation

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

## License

MIT
