# Cross-Agent Handoff Protocol

跨 agent handoff（派任务、转交工作）的强制规范。所有 agent 在执行 handoff 前必须遵循。

## 派任务

**跨 agent handoff 必须使用 `send-task`（生成 `request_task` 事件）。**

```bash
intent-broker send-task <targetParticipantId> <taskId> <threadId> <summary>
```

- `taskId` 必须非空，全局唯一
- 首次派单场景一律用 `send-task`
- broker 会为定向派单注册 5 分钟 watchdog，超时无 accept 则通知 PM

## 禁止的做法

| 命令 | 为什么不能用于派单 |
|------|-------------------|
| `report_progress` / `note` | 通知类事件，对方可以忽略，无任务生命周期 |
| `reply` | 依赖 `recentContext`，未收到过对方消息时不可用 |

`report_progress` 只能在已存在的 `taskId` 上追加状态。`reply` 只能回复已收到的消息。

## Handoff Checklist

每次 handoff 应包含：

1. 设计文档路径（`docs/` 下的最终版 spec）
2. PR 拆分与依赖顺序
3. 必改关键点列表（文件 + 行号）
4. 验收标准（完成后如何验证）

```bash
# 完整示例
intent-broker send-task codex-session-019e9a90 \
  "esc-interrupt-pr1a" \
  "esc-interrupt-implementation" \
  "Handoff: 实现 ESC 中断 PR1a-PR4. 设计文档: docs/2026-06-06-esc-pause-interrupt-design-v3.3.md. 从 PR1a 开始..."
```

## 查看任务状态

```bash
# 列出所有未确认任务
intent-broker tasks --status open

# 查看某个 agent 的任务
intent-broker tasks --assignee codex-session-019e9a90
```
