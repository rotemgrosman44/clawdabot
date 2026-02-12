# Skill Audit Policy (Post-Processing Skills)

## Mandatory Gates

1. Provenance must be pinned (zip checksum or git commit hash).
2. Manifest must be reviewed (purpose, boundaries, invocation).
3. Code scan must be completed for:
   - network calls
   - shell/child process execution
   - writes outside explicit output paths
4. Deterministic input->output contract is required.
5. Scope must remain post-processing only unless separately approved.

## Hard Reject

Do not install skills whose stated purpose is deception (for example, bypassing AI detectors).

## Evidence Commands

```bash
ls -la
find . -maxdepth 4 -type f | sed -n "1,200p"
rg -n "curl|wget|http|https|axios|fetch\(" -S . || true
rg -n "child_process|exec\(|spawn\(|subprocess|os\.system|system\(" -S . || true
rg -n "token|secret|api_key|authorization" -S . || true
```
