# kai-project-governance

> 多个 AI 智能体同时改一份代码库，会无声地互相踩踏——一个重构模块，另一个删掉它；第三个推送的提交与另外两个冲突。没人知道，直到出问题。kai-project-governance 是一个**并发安全 lint**，让工作区声明可见，在冲突造成破坏之前把它交给人类决策者。

适用于 [Claude Code](https://claude.ai/claude-code)、[Codex CLI](https://github.com/openai/codex)、[Antigravity](https://antigravity.dev) 及多智能体环境的并发冲突防护技能。

[English](README.md) | 简体中文

---

## 工作原理

### 三档行为模型

| 档 | 名称 | 何时生效 | 行为 |
|---|------|---------|------|
| 档1（默认）| **LINT** | 始终激活 | 冲突检测 + 警告。仅当冲突且无人在场时阻塞。 |
| 档2（必做）| **NOTIFY** | 每次提交/推送时 | 向 PM 发送非阻塞通知。永远不阻塞流程。 |
| 档3（可选）| **GATE** | 设置 `GOVERNANCE_MODE=gate` 时 | 每次提交/推送阻塞等待 PM 审批。120 秒超时后降级。 |

### 三层检查（档1 细节）

在每个受控行为（编辑、提交、删除、部署）前，技能执行三层检查：

```
动作触发 → 人在操作？
  → 是 → 显示冲突信息，放行（人类决策）
  → 否 → 与其他 agent 冲突？
    → 否 → 放行，记录日志
    → 是 → 请求 PM 审批（120 秒超时 → 降级放行）
```

**第 1 层 — 人在操作。** 如果人类正在驱动 agent（最近消息 < 5 分钟），显示冲突提示但不阻塞。人就是治理。

**第 2 层 — 冲突检测。** 检查 `.governance-claims/` 中其他 agent 的活跃声明，将 `files`、`directories`、`mayAffect` 与计划操作做交集。

**第 3 层 — PM 审批。** 无人操作且有冲突时，通过 intent broker 向 PM 请求审批。120 秒超时后降级放行并记录。

### 工作区声明（Workspace Claim）

每个 agent 在开始任务前声明自己要操作的文件：

```bash
python3 scripts/governance.py claim \
  --files src/main.py src/types.py \
  --dirs src/module/ \
  --may-affect src/shared/types.py
```

其他 agent 操作前检查：

```bash
python3 scripts/governance.py check --files src/main.py
# → {"hasConflict": false, "activeClaims": 0}
```

声明 30 分钟后过期（可配置）。长时间任务每 10 分钟续期。

### 它不做的事

这是一个**合作式 lint，不是硬锁**。不运行此技能的 agent 仍可编辑文件。如需硬强制，请使用 git hooks、CI 分支保护或文件权限——那些是不同层的防护。

---

## 安装

### Claude Code

```bash
ln -s /path/to/kai-project-governance ~/.claude/skills/kai-project-governance
```

### Codex CLI

```bash
ln -s /path/to/kai-project-governance ~/.codex/skills/kai-project-governance
```

### Antigravity (agy)

```bash
ln -s /path/to/kai-project-governance ~/.gemini/skills/kai-project-governance
```

### 其他 agent

```bash
ln -s /path/to/kai-project-governance ~/.agents/skills/kai-project-governance
```

安装后重启 agent。

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `governance.py claim --files ...` | 声明工作区文件/目录 |
| `governance.py check --files ...` | 操作前检查冲突 |
| `governance.py renew [--ttl N]` | 续期活跃声明 |
| `governance.py expand --files ...` | 任务中途扩展声明范围 |
| `governance.py release` | 释放工作区声明 |
| `governance.py notify --phase ...` | **档2**：非阻塞通知 PM |
| `governance.py request-approval --phase ...` | **档3**：阻塞审批请求（gate 模式） |
| `governance.py log --phase ... --status ...` | 记录治理动作日志 |
| `governance.py cleanup` | 清理过期/损坏的声明 |
| `governance.py status` | 显示当前治理状态 |

所有命令需在 git 仓库内执行。Agent 身份通过 `GOVERNANCE_AGENT_ID` 环境变量设置。

---

## 受控节点

| 节点 | 触发时机 | 严重度 |
|------|---------|--------|
| 规划 | 写 plan 文件前 | 中 |
| 实现 | 编辑源码文件前 | 中 |
| 破坏性 | 删除/重命名/移动文件前 | 严重 |
| 提交 | `git commit` / `git push` 前 | 高 |
| 配置 | 修改配置/依赖/环境文件前 | 高 |
| 验证 | 部署/发布操作前 | 高 |

严重操作即使人在操作也始终显示警告。

---

## 目录结构

```
kai-project-governance/
├── SKILL.md                    # 路由层：触发条件 + 治理流程
├── scripts/
│   ├── governance.py           # 确定性 CLI
│   └── run_evals.py            # 评估运行器
├── references/
│   ├── workspace-claims.md     # 声明协议 + 竞态缓解
│   ├── pm-governance.md        # PM 工作流
│   ├── broker-commands.md      # Intent broker CLI 参考
│   └── operation-severity.md   # 操作严重度分级
├── evals/
│   ├── eval-cases.json         # 12 个评估用例
│   ├── contract_checks.py      # 声明/日志/路径验证
│   ├── rubric.schema.json      # 评分维度
│   ├── failure-map.md          # 评估失败时指向修复方向
│   └── baseline-report.json   # 基线：12/12 通过，100%
└── tests/
    ├── test_contract_checks.py # 43 个单元测试
    ├── test_governance_cli.py  # 20 个集成测试
    ├── test_reference_integrity.py # 5 个完整性测试
    └── test_skill_size.py      # 1 个预算测试
```

---

## 评估框架

```bash
python3 scripts/run_evals.py
```

基线结果：**12/12 通过，100%，所有评分 5.0/5.0**

| 维度 | 检查内容 |
|------|---------|
| claim_protocol | 声明字段正确、本地存储、通过 broker 广播 |
| conflict_detection | 正确识别文件/目录/mayAffect 冲突 |
| degradation_handling | broker 不可用和 PM 超时时正确降级 |
| log_integrity | 日志条目 schema 正确、phase 和 status 合法 |

单元测试：`pytest tests/ -v` — 69 个测试全部通过。

---

## 设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 三档模型 | LINT + NOTIFY + GATE | 默认非阻塞，gate 按需启用 |
| 合作式，非强制 | 接受 | 硬强制属于 git hooks / CI 的职责 |
| 文件粒度 | 接受 | 函数级分析成本太高；假阳性优于假阴性 |
| 120 秒 PM 超时 → 降级 | 接受 | 永远不阻塞整个开发流程 |
| 人在操作时显示警告 | 接受 | 让人看到信息但不阻塞 |
| 本地文件作为声明真相来源 | 选择 | broker inbox 不是可靠的状态存储 |
| JSONL 每人一个日志文件 | 选择 | 避免并发写入损坏 |

### 已知局限

1. **非原子声明** — 两个 agent 可能同时声明同一文件。5 秒观察窗口缓解但无法消除。
2. **作用域漂移** — agent 发现需要改更多文件。增量扩展缓解。
3. **PM 单点** — 批量审批减少疲劳。
4. **仅文件级冲突** — 同文件不同函数的编辑会触发假警告。
5. **时钟偏移** — `expiresAt` 使用 agent 本地时间。影响有限。

---

## 兼容性

| 平台 | 安装路径 |
|------|---------|
| Claude Code | `~/.claude/skills/kai-project-governance/` |
| Codex CLI | `~/.codex/skills/kai-project-governance/` |
| Antigravity (agy) | `~/.gemini/skills/kai-project-governance/` |
| 通用 agent | `~/.agents/skills/kai-project-governance/` |
