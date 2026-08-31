---
name: exec-report-writing
description: Convert technical notes, implementation details, project updates, incident reviews, or design documents into concise leadership-ready reports. Use when Codex should help the user understand complex material, rewrite content for executives, prepare a Feishu/Lark document for management reporting, reduce code-level detail, or produce a structured report with conclusions, business value, process explanation, progress, risks, and next steps.
---

# Executive Report Writing

Use this skill to turn technical material into a report the user can understand quickly and use with leaders. Keep enough technical truth to be credible, but move implementation details out of the main narrative.

## Core Workflow

1. **Clarify the audience and purpose.**
   Identify whether the report is for a direct manager, senior leadership, cross-functional stakeholders, or the user's own understanding. If unclear, assume senior leadership and write for fast decision-making.

2. **Extract the message from the material.**
   Read source notes, docs, diffs, meeting notes, or existing Lark/Feishu content. Separate facts from implementation details:
   - Business problem or opportunity.
   - What changed or what is proposed.
   - Why it matters.
   - Current status and evidence.
   - Risks, boundaries, and asks.

3. **Front-load the conclusion.**
   Start with one short executive conclusion: what was done, what problem it solves, and what value it creates.

4. **Explain the process without code-level noise.**
   Replace function names, commands, file trees, and long code snippets with process language:
   - "系统做什么"
   - "为什么重要"
   - "产出什么"
   - "对业务或质量有什么影响"

5. **Structure for scanning.**
   Prefer callouts, tables, short numbered steps, comparison grids, risk tables, and next-step lists. Avoid long uninterrupted paragraphs.

6. **Preserve technical accuracy.**
   Keep necessary terms such as RAG, embedding, chunk, tokenizer, API, or fallback, but explain their role in plain business language. Do not invent metrics or outcomes unless the source provides them.

## Recommended Report Shape

Use this default outline unless the user's material suggests a better one:

1. **核心结论**
   One paragraph or callout. State the outcome and value.

2. **背景与问题**
   Why this matters now. Describe pain points in user/business terms, not internal code terms.

3. **方案概览**
   What the solution does at a high level. Use 2-4 pillars or a short table.

4. **过程说明**
   Explain the workflow step by step. For each step, include:
   - 系统做什么
   - 为什么重要
   - 产出什么

5. **能力收益 / 业务价值**
   Tie technical changes to outcomes: quality, efficiency, stability, scalability, risk reduction, or governance.

6. **当前进展**
   Use status wording: 已完成、推进中、待验证、需决策. Keep this factual.

7. **风险与边界**
   Name limitations honestly and pair each with mitigation.

8. **后续建议**
   Provide 3-5 concrete next actions. Prefer verbs: 灰度、验证、沉淀、治理、对齐.

## Style Rules

- Write in Chinese by default when the user speaks Chinese or the target is Lark/Feishu.
- Use "领导汇报版" tone: direct, concrete, confident, not promotional.
- Keep code out of the main report unless the user explicitly asks for a technical appendix.
- Do not over-explain basic engineering concepts; explain only what affects business understanding or decisions.
- Avoid phrases like "我们通过某某函数实现". Prefer "系统先识别结构，再判断语义边界".
- Avoid huge sections named "实现文件索引", "运行方式", "测试命令" in leadership reports. Summarize as "验证方式" or "当前完成情况".
- Use tables when comparing problems, changes, benefits, risks, or statuses.
- Use a short "落到效果上" paragraph to connect process to business value.
- If updating a Lark/Feishu document, combine this skill with `lark-doc`; use this skill for content strategy and `lark-doc` for document operations.

## Useful Blocks

### Executive Conclusion

```text
核心结论：我们已将【旧能力/旧流程】升级为【新能力/新流程】。新方案解决了【核心问题】，能提升【关键质量/效率/稳定性】，为后续【业务目标/系统目标】打基础。
```

### Process Table

| 步骤 | 系统做什么 | 为什么重要 | 产出 |
| --- | --- | --- | --- |
| 1. 读取输入 | 识别基础结构和关键信息 | 避免直接处理混乱文本 | 得到可分析内容 |
| 2. 判断边界 | 判断哪些内容应该合并或切开 | 保证上下文完整 | 得到稳定单元 |
| 3. 质量兜底 | 控制过短、过长、异常场景 | 保证下游可稳定消费 | 得到标准输出 |

### Risk Table

| 风险点 | 说明 | 应对方式 |
| --- | --- | --- |
| 数据质量不稳定 | 输入缺失、冲突或结构混乱会影响结果 | 建立抽检和治理机制 |
| 参数不适配 | 不同业务可能需要不同阈值 | 通过评测沉淀基线 |
| 边界场景复杂 | 极端内容可能仍需特殊处理 | 保留 fallback 和人工复核 |

## Quality Checklist

Before finalizing, verify:

- The first screen gives the conclusion and why it matters.
- A leader can understand the process without reading code.
- The report says what changed, what value it creates, and what remains risky.
- Technical claims are defensible from the source material.
- Tables or structured blocks replace long lists where useful.
- There is a clear "next step" section.
