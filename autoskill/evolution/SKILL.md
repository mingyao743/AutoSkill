---
name: autoskill-evolution
description: "AutoSkill Evolution: autonomous skill optimizer based on darwin-skill 2.0. Evaluates SKILL.md using a 9-dimension rubric (structure + effectiveness + meta-skill blacklists), runs hill-climbing with git version control, spawns independent judge agents for blind evaluation, validates improvements through test prompts with auto-break on diminishing returns. Triggered automatically when skill provenance accumulates. Use when system triggers skill evolution, optimization, or quality improvement."
---

# AutoSkill Evolution

> 基于 [darwin-skill 2.0](https://github.com/alchaincyf/darwin-skill)，吸收 Microsoft Research SkillLens（arXiv 2605.23899）9 维 rubric + SkillOpt（arXiv 2605.23904）validation-gated 设计。
>
> 核心理念：**评估 → 改进 → 实测验证 → 保留或回滚 → 回写 SkillBank**
>
> **全自动模式**：无 checkpoint 暂停，棘轮机制 + paired 比较 + 反模式黑名单保障质量。

---

## 设计哲学

1. **单一可编辑资产** — 每次只改一个 SKILL.md
2. **双重评估** — 结构评分（静态分析）+ 效果验证（跑测试看输出）
3. **棘轮机制** — 只保留改进，自动回滚退步
4. **独立评分** — 评分用子 agent，避免「自己改自己评」的偏差（SkillLens 实证 LLM 自评仅 46.4%）
5. **全自动运行** — 由系统触发，无需人工确认；paired 比较 + 反模式黑名单替代人工守关

---

## 评估 Rubric（9 维度，总分 100）

> **设计依据**：SkillLens 论文实证——LLM-as-judge 准确率仅 46.4%，加入 meta-skill 三维度后提升到 73.8%。

### 结构维度（59 分）— 静态分析

| # | 维度 | 权重 | 评分标准 |
|---|------|------|---------|
| 1 | **Frontmatter 质量** | 7 | name 规范、description 包含做什么+何时用+触发词、≤1024 字符、禁结尾加空话 |
| 2 | **工作流清晰度** | 12 | 步骤明确可执行、有序号、每步有明确输入/输出 |
| 3 | **失败模式编码** | 12 | 必须显式编码失败模式（"如果 X 失败 → Y"）；有 fallback 路径、错误恢复；只写正向流程不写失败分支扣 ≥3 分 |
| 4 | **检查点设计** | 6 | 关键决策前有用户确认、防止自主失控；检查点必须显性标记 |
| 5 | **可执行具体性** | 18 | 不模糊、有具体参数/格式/示例；禁止"建议/可以考虑/根据情况/灵活把握/视情况而定"等软化措辞——出现 ≥3 处扣 ≥3 分 |
| 6 | **资源整合度** | 4 | references/scripts/assets 引用正确、路径可达 |

### 效果维度（35 分）— 需要实测

| # | 维度 | 权重 | 评分标准 |
|---|------|------|---------|
| 7 | **整体架构** | 12 | 结构层次清晰、不冗余不遗漏 |
| 8 | **实测表现** | 23 | 用测试 prompt 跑一遍，输出质量是否符合 skill 宣称的能力 |

### Meta-skill 维度（6 分）— 反例与黑名单

| # | 维度 | 权重 | 评分标准 |
|---|------|------|---------|
| 9 | **反例与黑名单** | 6 | skill 必须有"不要做什么"的反例清单；红灯/危险动作/反模式应单独章节列出 |

### 评分规则
- 维度 1-7、9：每个维度打 1-10 分，乘以权重得到该维度得分
- 维度 8（实测表现）：跑 2-3 个测试 prompt，按输出质量打 1-10 分
- **总分 = Σ(维度分 × 权重) / 10**，满分 100
- **绝对总分只用于 triage**（决定先改谁），**绝不用于 keep/revert**。keep/revert 一律走 Phase 2 的 paired 比较。
  - 原因：LLM judge 绝对分 ±8 噪音，paired 同 judge 比较消除换尺污染。

### 关于「实测表现」维度

1. 为每个 skill 设计 2-3 个典型用户 prompt（happy path + 歧义场景）
2. 用子 agent 执行：一个带 skill 跑，一个不带 skill 跑（baseline）
3. 对比输出质量打分

若子 agent 不可用，退化为干跑验证（读完 skill 后模拟执行思路），必须在 results.tsv 标注 `dry_run`。**dry_run 比例 > 30% → 评估失效警告**。

---

## 自主优化循环

### Phase 0: 初始化

```
1. 确定优化目标：
   - 系统指定要进化的 skill（由触发器传入 skill_id）
   - 从 SkillBank 读取 SKILL.md
2. 创建 git 分支：evo/YYYYMMDD-HHMM-{skill-slug}
3. 初始化 results.tsv（如不存在）
4. 读取现有 results.tsv 了解历史优化记录
```

### Phase 0.5: 测试 Prompt 设计

```
1. 读取 SKILL.md，理解它做什么
2. 设计 2-3 个测试 prompt，覆盖：
   - 最典型的使用场景（happy path）
   - 一个稍复杂或有歧义的场景
3. 如果有历史 provenance 数据，从中提取真实用户输入作为测试 prompt
4. 保存到 skill 目录/test-prompts.json
```

### Phase 1: 基线评估（triage 用途）

> 绝对分数是 triage 排名用途，不是 keep/revert 基准。

```
1. 读取 SKILL.md 全文
2. 按维度 1-7、9 逐项打分（附简短理由）
3. 对每个测试 prompt，spawn 子 agent：
   - with_skill: 带着 SKILL.md 执行测试 prompt
   - baseline: 不带 skill 执行同一 prompt
4. 对比两组输出，打维度 8 的分
5. 计算加权总分，记录到 results.tsv
```

### Phase 2: 优化循环

```
round = 0
while round < MAX_ROUNDS (默认 3):
  round += 1

  # Step 1: 诊断
  找出加权短板最大的维度：weighted_gap = weight × (10 - score) / 10
  # 加权短板相近（差距 ≤ 1.0）时，回退为原始分升序
  # dim2/dim3/dim4 是相关簇，修一个时另两个常跟着涨
  # → 看整簇短板再决定是否同步改

  # Step 2: 提出改进方案
  针对该维度，生成 1 个具体改进方案：
    - 改什么（具体段落/行）
    - 为什么改（对应 rubric 哪条）
    - 预期提升多少分

  # Step 3: 执行改进
  编辑 SKILL.md
  git add + commit（message: "evo {skill}: {改进摘要}"）

  # Step 4: Paired 重新评估
  spawn N=3 独立 judge，每个在同一次 call 内读两版：
    - 改前版：git show HEAD~1:<skill-path>/SKILL.md
    - 改后版：当前 SKILL.md
  照 9 维 rubric 当比较准则，回 {better | worse | tie} + margin{clear|slight} + 一句理由
  N 取奇数（默认 3；close call 升 5）

  # Step 5: 共识决策（多数决）
  cur = 投 better 的 judge 数；wor = 投 worse 的；
  if cur >= wor:  # 多数说改后 ≥ 改前（含 tie）
    status = "keep"
    # 连续 2 轮多数 judge 判 margin=slight 或 tie → break
  else:           # 多数说 worse —— 真退步
    status = "revert"
    git revert HEAD（不用 reset --hard）
    记录到 results.tsv
    break

  # Step 6: 日志
  results.tsv 追加行
```

### Phase 2.5: 探索性重写（按需触发）

当 hill-climbing 连续 2 个 skill 都在 round 1 就 break（涨不动）时：

```
1. git stash 保存当前最优版本
2. 从头重写 SKILL.md（不是微调，是重新组织结构和表达方式）
3. 重新评估
4. if 重写版 > stash 版: 采用重写版
   else: git stash pop 恢复
```

### Phase 3: 汇总 & 回写 SkillBank

```
1. 汇总本轮进化结果：
   - 分数变化
   - 保留/回滚次数
   - 主要改进摘要
2. 记录到 results.tsv
3. 回写 SkillBank：
   - 将最终 champion SKILL.md 复制到 SkillBank 对应 skill 目录
   - 版本号 +1（patch 版本）
   - 追加 version_history 记录
4. 触发 mirror：
   - 通知系统重新 mirror skill 到 agent 工作区
```

---

## results.tsv 格式

```tsv
timestamp	commit	skill	old_score	new_score	status	dimension	note	eval_mode
2026-10-16T10:00	baseline	some-skill	-	78	baseline	-	初始评估	full_test
2026-10-16T10:05	a1b2c3d	some-skill	78	84	keep	边界条件	补充 fallback	paired
2026-10-16T10:10	b2c3d4e	some-skill	84	82	revert	指令具体性	过度细化	paired
```

`eval_mode` 列：`paired`（keep/revert 权威依据）| `full_test`（子 agent 跑 prompt）| `dry_run`（模拟推演）

---

## 实战 high-leverage 操作

4 条经实战验证的杠杆操作：

- **HL-1（dim4）显性视觉标记是杠杆**：加 🔴 CHECKPOINT / 🛑 STOP，靠「必须」措辞不行——LLM 解析时扫描视觉标记
- **HL-2（dim3）if-then 三段式 fallback 表**：「触发条件 / 一线修复 / 仍失败兜底」三段式
- **HL-3（Phase 2 诊断）维度相关簇警告**：dim2/3/4 是相关簇——修 dim3 时 dim2 常跟着涨
- **HL-4（Phase 2 退出）触顶自动 break**：连续 2 轮 Δ < 2 分 → break；+0.15 是停手信号

---

## 优化策略库

按优先级排序，每轮只做最高优先级的一个：

### P0: 效果问题（实测发现的）
- 测试输出偏离用户意图 → 检查 skill 是否有误导性指令
- 带 skill 比不带还差 → skill 可能过度约束，考虑精简
- 输出格式不符合预期 → 补充明确的输出模板

### P1: 结构性问题
- Frontmatter 缺少触发词 → 补充中英文触发词
- 缺少 Phase/Step 结构 → 重组为线性流程
- 缺少用户确认检查点 → 在关键决策处插入

### P2: 具体性问题
- 步骤模糊 → 改为具体操作和参数
- 缺少输入/输出规格 → 补充格式、路径、示例
- 缺少异常处理 → 补充 "如果 X 失败，则 Y"

### P3: 可读性问题
- 段落过长 → 拆分+用表格
- 重复描述 → 合并去重
- 缺少速查 → 添加 TL;DR 或决策树

---

## 异常与边界条件

| 场景 | 触发条件 | 处理动作 |
|---|---|---|
| 不在 git 仓库 | `git rev-parse` 失败 | `cp SKILL.md SKILL.md.bak.YYYYMMDD-HHMM` 代替 revert |
| results.tsv 缺失 | 文件不存在 | 新建并写表头行 |
| results.tsv 损坏 | 列数不匹配 / 非 TSV | 备份后重建 |
| 分支已存在 | `git checkout -b` 失败 | 分支名末尾加 `-2` / `-3` |
| `git revert` 失败 | 冲突 / 工作树脏 | 先 `git stash`，重试；仍失败则从上一个 commit 恢复 |
| MAX_ROUNDS 触顶 | 已跑 3 轮仍有短板 | 自动进入 Phase 3 收工 |
| 优化后超 150% 体积 | 新文件 > 原 × 1.5 | 拒绝提交，精简后再评 |
| test-prompts.json 已存在 | 文件已在 skill 目录 | 默认复用 |
| SKILL.md 找不到 | 目录存在但无 SKILL.md | 该 skill 终止，results.tsv 记 `status=error` |
| 分数计算规则 | 浮点精度漂移 | 总分保留 1 位小数 |

**原则**：异常按规则处理，记录到 results.tsv，不静默跳过。

---

## 反模式黑名单（darwin 优化时不要做的事）

| # | 反模式 | 为什么不要做 | 替代做法 |
|---|---|---|---|
| 1 | **同 context 自评自改** | 乐观偏差（SkillLens 实证 LLM 自评仅 46.4%）| 必须 spawn **独立子 agent**；keep/revert 走 **paired 比较**的**奇数 N 多数决** |
| 1b | **拿绝对分数 delta 当 keep/revert 棘轮** | 绝对分是抽样不是测量；跨 judge ±8 噪音 | 绝对分只做 triage；keep/revert 用 paired 多数决 |
| 2 | **`git reset --hard` 当回滚** | 会丢工作树未提交改动 | 用 `git revert HEAD` |
| 3 | **为凑分增冗余** | 触顶后继续硬改往往是加废话 | 触顶信号 → break 进 Phase 3 |
| 4 | **跳过 test-prompts 直接评分** | dim8 权重 23% 等于编造 | 强制至少 1 个真实 full_test |
| 5 | **轮内改多个维度** | 多变量同时变，无法归因 | 每轮 1 个维度 |
| 6 | **dry_run 比例 > 30%** | dim8 形同虚设 | 强制至少 1 个 full_test |
| 7 | **静默跳过异常** | 破坏 ratchet 完整性 | 异常表 fallback 必须执行 |
| 8 | **忽视维度相关性单独优化** | dim2/3/4 是相关簇 | 找最大加权短板时同时看相关簇 |

**触发场景**：每轮 Phase 2 改动前对照本表一次。任一反模式命中 → 改方案重写。

---

## 约束规则

1. **不改变 skill 的核心功能和用途** — 只优化"怎么写"和"怎么执行"
2. **不引入新依赖** — 不添加 skill 原本没有的 scripts 或 references
3. **每轮只改一个维度** — 避免多个变更导致无法归因
4. **保持文件大小合理** — 优化后 SKILL.md 不应超过原始大小的 150%
5. **可回滚** — 所有改动在 git 分支上，用 git revert 而非 reset --hard
6. **评分独立性** — 效果维度必须用子 agent 或至少干跑验证
7. **Runtime 中立性** — skill 必须能在任何 skills-compatible runtime 中正常运行

---

## 触发方式

本 skill 由 AutoSkill 系统自动触发，非用户手动调用：

```
触发条件：
  sdk.ingest() 完成后，检查目标 skill 的 provenance 增量
  if 新增 replay 数 >= 阈值（默认 5 条）:
    调度本 skill 对目标 skill 执行进化

输入参数：
  - skill_id: 要进化的 skill 标识
  - skill_dir: skill 在 SkillBank 中的目录路径
  - provenance_dir: 历史对话数据目录

执行完成后：
  - champion 回写 SkillBank
  - 触发 mirror 更新 agent 工作区
```

---

## 学术依据

- **SkillLens**（arXiv [2605.23899](https://arxiv.org/abs/2605.23899)）：9 维 rubric 实证来源
- **SkillOpt**（arXiv [2605.23904](https://arxiv.org/abs/2605.23904)）：validation-gated edits 框架
- **darwin-skill**（[github.com/alchaincyf/darwin-skill](https://github.com/alchaincyf/darwin-skill)）：本系统的 prompt 基础
- **autoresearch**（[github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)）：原始灵感
