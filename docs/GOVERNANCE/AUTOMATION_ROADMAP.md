# Automation Roadmap / 自动化路线图

## Scope / 范围
This repo is **not** the pilot for Issue → PR automation. It documents the roadmap only. / 本仓库非试点，仅记录路线图。

## Phase 1 (Pilot in another repo) / 第一阶段（在其他仓库试点）
- Trigger: issue labeled `ready-for-dev`
- Validate required fields (Goal/Scope/Acceptance/Risk)
- Create draft PR with `Closes #<issue>` and plan template

## Phase 2 (Future) / 第二阶段
- Integrate local Codex executor (out of scope)
- Human review remains mandatory

## Audit & Rollback / 审计与回滚
- All automation actions are logged
- Remove workflow file to disable
- Draft PRs can be closed without impact
