# AutoSkill Core: SDK, Runtime, and Evolution

English | [中文](README.zh-CN.md)

Project Root: [../README.md](../README.md)

This document covers the core `autoskill/` package: SDK APIs, skill extraction and maintenance, proxy runtime, offline extraction, and darwin-skill based self-evolution.

## Table of Contents

- [1. Quick Start](#1-quick-start)
- [2. Core Workflow](#2-core-workflow)
- [3. SkillBank Storage Layout](#3-skillbank-storage-layout)
- [4. Package Structure](#4-package-structure)
- [5. SDK Usage](#5-sdk-usage)
- [6. Provider Setup](#6-provider-setup)
- [7. Runtime APIs](#7-runtime-apis)

## 1. Quick Start

### Web UI

```bash
pip install -e .
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.web_ui \
  --host 127.0.0.1 \
  --port 8000 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --store-dir SkillBank \
  --user-id u1 \
  --extract-mode auto
```

### OpenAI-Compatible Proxy

```bash
python3 -m examples.openai_proxy \
  --host 127.0.0.1 \
  --port 9000 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --served-model your-model \
  --store-dir SkillBank
```

Endpoints:
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`
- `GET /health`

## 2. Core Workflow

### Extract and Maintain

```text
Experience (messages/events)
  -> Skill Extraction (LLM candidate)
  -> Skill Maintenance (add / merge / discard)
  -> Skill Store (SKILL.md + vector index)
```

- Extractor emits at most one high-quality candidate per attempt
- Maintainer checks similarity against existing skills, decides add/merge/discard
- Merge updates preserve capabilities and bump patch version

### Mirror and Load

```text
SkillBank
  -> Mirror to Agent Workspace (~/.pi/agent/skills/)
  -> Agent natively discovers and loads skills
```

- Skills are mirrored as `SKILL.md` files with managed markers
- Agent's native progressive loader discovers skills without retrieval overhead
- Mirror is stable: no duplicate clones on re-mirror

### Self-Evolution

```text
Provenance accumulates
  -> Trigger evolution check
  -> Darwin-skill loop:
     1. 9-dimension rubric evaluation
     2. Paired comparison (N=3 judges, majority vote)
     3. Hill-climbing mutation (one dimension per round)
     4. Keep/revert via git ratchet
     5. Write back champion to SkillBank
```

- Triggered automatically when skill provenance reaches threshold (default: 5 records)
- Evolution skill: [`autoskill/evolution/SKILL.md`](evolution/SKILL.md)
- Based on [darwin-skill 2.0](https://github.com/alchaincyf/darwin-skill)

## 3. SkillBank Storage Layout

```text
SkillBank/
  Users/
    <user_id>/
      <skill-slug>/
        SKILL.md
        scripts/          (optional)
        references/       (optional)
        assets/           (optional)
  Common/
    <skill-slug>/SKILL.md
    <library>/<skill-slug>/SKILL.md
  vectors/
    <embedding-signature>.meta.json
    <embedding-signature>.ids.txt
    <embedding-signature>.vecs.f32
  index/
    skills-bm25.*          (BM25 index)
    online_skill_provenance_<user>.json  (provenance tracking)
```

## 4. Package Structure

### Core SDK

- `client.py`: public SDK (`ingest`, `search`, import/export)
- `config.py`: global config model
- `models.py`: core data models (`Skill`, `SkillHit`)
- `skill_provenance.py`: provenance tracking and version history
- `llm/`: pluggable LLM backends
- `embeddings/`: pluggable embedding backends

### Skill Management

- `management/extraction.py`: extraction logic and prompts
- `management/maintenance.py`: merge, version, add/discard decisions
- `management/formats/agent_skill.py`: `SKILL.md` render and parse
- `management/stores/local.py`: directory-based storage + vector mapping
- `management/importer.py`: import external Agent Skills

### Interactive Layer

- `interactive/app.py`: terminal interactive app
- `interactive/session.py`: headless session engine
- `interactive/server.py`: OpenAI-compatible proxy runtime
- `interactive/unified.py`: unified composition root
- `interactive/config.py`: interactive configuration

### Offline Layer

- `offline/conversation/extract.py`: import OpenAI-format conversations
- `offline/trajectory/extract.py`: import agentic trajectory data
- `evolution/SKILL.md`: darwin-skill based self-evolution prompt

### Examples

- `examples/web_ui.py`: local Web UI server
- `examples/interactive_chat.py`: CLI interactive chat
- `examples/openai_proxy.py`: OpenAI-compatible proxy

## 5. SDK Usage

```python
from autoskill import AutoSkill, AutoSkillConfig

sdk = AutoSkill(
    AutoSkillConfig(
        llm={"provider": "mock"},
        embeddings={"provider": "hashing", "dims": 256},
        store={"provider": "local", "path": "SkillBank"},
    )
)

sdk.ingest(
    user_id="u1",
    messages=[
        {"role": "user", "content": "Before each release: run regression -> canary -> monitor -> full rollout."},
        {"role": "assistant", "content": "Understood."},
    ],
)

hits = sdk.search("How should I do a safe release?", user_id="u1", limit=3)
for h in hits:
    print(h.skill.name, h.score)
```

### Offline Conversation Extraction

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./data/conversations.jsonl \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope
```

### Offline Trajectory Extraction

```bash
python3 -m autoskill.offline.trajectory.extract \
  --file ./data/traces \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --success-only 1 \
  --include-tool-events 1
```

## 6. Provider Setup

### DashScope

```bash
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.interactive_chat --llm-provider dashscope
```

### OpenAI / Anthropic

```bash
export OPENAI_API_KEY="YOUR_OPENAI_KEY"
python3 -m examples.interactive_chat --llm-provider openai

export ANTHROPIC_API_KEY="YOUR_ANTHROPIC_KEY"
python3 -m examples.interactive_chat --llm-provider anthropic
```

### Generic URL-based Backends

```bash
export AUTOSKILL_GENERIC_LLM_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_LLM_MODEL="your-model"
export AUTOSKILL_GENERIC_EMBED_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_EMBED_MODEL="your-embed-model"

python3 -m examples.interactive_chat --llm-provider generic --embeddings-provider generic
```

## 7. Runtime APIs

### Interactive Chat Commands

- `/extract_now [hint]` — force immediate extraction
- `/extract_every <n>` — set extraction interval
- `/extract auto|always|never` — set extraction mode
- `/skills` — list current skills
- `/export <skill_id>` — export skill

### Proxy API

```bash
# Discover capabilities
curl http://127.0.0.1:9000/v1/autoskill/capabilities
curl http://127.0.0.1:9000/v1/autoskill/openapi.json
```

Skill management:
- `GET /v1/autoskill/skills`
- `GET /v1/autoskill/skills/{skill_id}`
- `PUT /v1/autoskill/skills/{skill_id}/md`
- `DELETE /v1/autoskill/skills/{skill_id}`
- `POST /v1/autoskill/skills/search`

Extraction:
- `POST /v1/autoskill/extractions`
- `POST /v1/autoskill/extractions/simulate`
- `GET /v1/autoskill/extractions/latest`
