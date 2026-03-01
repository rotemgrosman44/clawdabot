# Cron Jobs Registry (Gateway Scheduler)

## Source of truth
- Built from OpenClaw Gateway Web UI evidence (screenshots / export)
- No job changes executed during this phase

## Schema (per job)
- name
- schedule (cron)
- state: enabled | disabled | isolated | error
- target agent
- description
- inputs (observed)
- outputs (observed)
- artifact paths (if any)
- dependencies (suspected)
- evidence (screenshot filename)

---

## Jobs
<!-- Fill sequentially: 001..027 -->

---

## Dependency Map & Collision Analysis (append after registry complete)
### Buckets
- CORE
- DEPENDENT
- ITERATION / QUALITY LOOP
- EXPERIMENTAL
- LEGACY

### Suspected collisions to verify
- Gmail Plumber -> Morning Brief (feed vs duplicate)
- SEO Sentinel overlaps
- Duplicate iteration windows vs publish logic
- Multiple jobs writing to same artifact paths
