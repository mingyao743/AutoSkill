# AutoSkill 核心：SDK、运行时与进化

[English](README.md) | 中文

项目根目录：[../README.md](../README.md)

本文档涵盖核心 `autoskill/` 包：SDK API、技能提取与维护、代理运行时、离线提取，以及基于 darwin-skill 的自进化。

## 目录

- [1. 快速开始](#1-快速开始)
- [2. 核心工作流](#2-核心工作流)
- [3. SkillBank 存储结构](#3-skillbank-存储结构)
- [4. 包结构](#4-包结构)
- [5. SDK 使用](#5-sdk-使用)
- [6. 提供商配置](#6-提供商配置)
- [7. 运行时 API](#7-运行时-api)

## 1. 快速开始

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

### OpenAI 兼容代理

```bash
python3 -m examples.openai_proxy \
  --host 127.0.0.1 \
  --port 9000 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --served-model your-model \
  --store-dir SkillBank
```

端点：
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`
- `GET /health`

## 2. 核心工作流

### 提取与维护

```text
经验 (消息/事件)
  -> 技能提取 (LLM 候选)
  -> 技能维护 (添加 / 合并 / 丢弃)
  -> 技能存储 (SKILL.md + 向量索引)
```

- 每次尝试最多提取一个高质量候选
- 维护器检查与现有技能的相似度，决定添加/合并/丢弃
- 合并更新保留能力并升级补丁版本

### 镜像与加载

```text
SkillBank
  -> 镜像到 Agent 工作区 (~/.pi/agent/skills/)
  -> Agent 原生发现并加载技能
```

- 技能以 `SKILL.md` 文件形式镜像，带管理标记
- Agent 的原生渐进式加载器发现技能，无需检索开销
- 镜像稳定：重新镜像不会产生重复克隆

### 自进化

```text
Provenance 累积
  -> 触发进化检查
  -> Darwin-skill 循环：
     1. 9 维 rubric 评估
     2. 配对比较 (N=3 评委，多数决)
     3. 爬山变异 (每轮一个维度)
     4. 通过 git 棘轮保留/回滚
     5. 将 champion 回写 SkillBank
```

- 当技能 provenance 达到阈值时自动触发 (默认：5 条记录)
- 进化技能：[`autoskill/evolution/SKILL.md`](evolution/SKILL.md)
- 基于 [darwin-skill 2.0](https://github.com/alchaincyf/darwin-skill)

## 3. SkillBank 存储结构

```text
SkillBank/
  Users/
    <user_id>/
      <skill-slug>/
        SKILL.md
        scripts/          (可选)
        references/       (可选)
        assets/           (可选)
  Common/
    <skill-slug>/SKILL.md
    <library>/<skill-slug>/SKILL.md
  vectors/
    <embedding-signature>.meta.json
    <embedding-signature>.ids.txt
    <embedding-signature>.vecs.f32
  index/
    skills-bm25.*          (BM25 索引)
    online_skill_provenance_<user>.json  (provenance 追踪)
```

## 4. 包结构

### 核心 SDK

- `client.py`: 公共 SDK (`ingest`, `search`, 导入/导出)
- `config.py`: 全局配置模型
- `models.py`: 核心数据模型 (`Skill`, `SkillHit`)
- `skill_provenance.py`: provenance 追踪和版本历史
- `llm/`: 可插拔 LLM 后端
- `embeddings/`: 可插拔 embedding 后端

### 技能管理

- `management/extraction.py`: 提取逻辑和提示词
- `management/maintenance.py`: 合并、版本、添加/丢弃决策
- `management/formats/agent_skill.py`: `SKILL.md` 渲染和解析
- `management/stores/local.py`: 基于目录的存储 + 向量映射
- `management/importer.py`: 导入外部 Agent Skills

### 交互层

- `interactive/app.py`: 终端交互式应用
- `interactive/session.py`: 无头会话引擎
- `interactive/server.py`: OpenAI 兼容代理运行时
- `interactive/unified.py`: 统一组合根
- `interactive/config.py`: 交互配置

### 离线层

- `offline/conversation/extract.py`: 导入 OpenAI 格式对话
- `offline/trajectory/extract.py`: 导入 agent 轨迹数据
- `evolution/SKILL.md`: 基于 darwin-skill 的自进化提示词

### 示例

- `examples/web_ui.py`: 本地 Web UI 服务器
- `examples/interactive_chat.py`: CLI 交互式聊天
- `examples/openai_proxy.py`: OpenAI 兼容代理

## 5. SDK 使用

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
        {"role": "user", "content": "每次发布前：回归测试 -> 金丝雀 -> 监控 -> 全量发布。"},
        {"role": "assistant", "content": "明白。"},
    ],
)

hits = sdk.search("如何安全发布？", user_id="u1", limit=3)
for h in hits:
    print(h.skill.name, h.score)
```

### 离线对话提取

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./data/conversations.jsonl \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope
```

### 离线轨迹提取

```bash
python3 -m autoskill.offline.trajectory.extract \
  --file ./data/traces \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --success-only 1 \
  --include-tool-events 1
```

## 6. 提供商配置

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

### 通用 URL 后端

```bash
export AUTOSKILL_GENERIC_LLM_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_LLM_MODEL="your-model"
export AUTOSKILL_GENERIC_EMBED_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_EMBED_MODEL="your-embed-model"

python3 -m examples.interactive_chat --llm-provider generic --embeddings-provider generic
```

## 7. 运行时 API

### 交互式聊天命令

- `/extract_now [hint]` — 强制立即提取
- `/extract_every <n>` — 设置提取间隔
- `/extract auto|always|never` — 设置提取模式
- `/skills` — 列出当前技能
- `/export <skill_id>` — 导出技能

### 代理 API

```bash
# 发现能力
curl http://127.0.0.1:9000/v1/autoskill/capabilities
curl http://127.0.0.1:9000/v1/autoskill/openapi.json
```

技能管理：
- `GET /v1/autoskill/skills`
- `GET /v1/autoskill/skills/{skill_id}`
- `PUT /v1/autoskill/skills/{skill_id}/md`
- `DELETE /v1/autoskill/skills/{skill_id}`
- `POST /v1/autoskill/skills/search`

提取：
- `POST /v1/autoskill/extractions`
- `POST /v1/autoskill/extractions/simulate`
- `GET /v1/autoskill/extractions/latest`
