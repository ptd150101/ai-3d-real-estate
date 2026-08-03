# P2 threat model

| Boundary | Primary threats | Controls |
|---|---|---|
| Multi-tenant API | IDOR and cross-agency reads/writes | Mandatory organization context, membership role, server-side feature gates and tenant isolation tests |
| Payments | Replay, forged callback, duplicate money movement | Provider signature verification, unique event/idempotency keys, monotonic state machine and immutable balanced ledger |
| Contracts | Silent document replacement and forged events | Legal policy allowlist, PDF checksum, append-only evidence and ordered/idempotent events |
| Upload/reconstruction | Malicious file, resource exhaustion | MIME/size/hash validation, private capture storage, isolated GPU queue, timeout and human review gate |
| Mobile | Token theft and duplicate offline writes | SecureStore, hashed rotating refresh tokens, device binding, revoke endpoint and client mutation IDs |
| AI | Unsupported confident output and model regression | Segment/time evaluation, confidence range, insufficient-data response, promotion gate and drift kill switch |
| AR/VR | Unsupported device dead end or camera privacy | Capability detection, static fallback and no camera upload without explicit capture action |
