# TLA+ models of the concurrency (record, not a gate)

Two small models of what the parallel line-run relies on, checked with TLC on 2026-09-23
(tla2tools latest release, OpenJDK 27). TLC is not part of `.claude/verify.sh` — Java is
not a commit-gate dependency (judge decision 2026-09-23). Re-run by hand when the code the
model mirrors changes.

```bash
java -cp ~/.local/lib/tla2tools.jar tlc2.TLC -config <cfg> -deadlock <Spec>.tla
```

| model | mirrors | config | expected | result |
|---|---|---|---|---|
| StageConcurrency | `LineRun._jev`, `StoredJev.judge`, `JevClient.judge` | `SC_asbuilt.cfg`, `SC_asbuilt6.cfg` | every invariant holds | holds |
| | cap read before the slot | `SC_precheck_k6.cfg` | overshoot beyond the in-flight bound | `OvershootInFlight` violated |
| | cost counted on completion (Qwen tokens) | `SC_qwen_k6.cfg` | overshoot up to the in-flight bound, not beyond | holds (`OvershootOneRequest` alone is violated) |
| | no single-flight | `SC_nosingle.cfg` | an identical judgment sent twice | `NoDuplicateRequest` violated |
| BatchSplit | `JevClient.judge_batch` halving | `BS_size1.cfg`, `BS_size2.cfg` | the bad items sink alone, ≤ 2N−1 requests | holds |
| | fixed policy, shared refusal | `BS_sharedfixed.cfg` | one request | holds |
| | old policy (split on any 4xx) | `BS_sharedold.cfg` | more than one request | `SharedPaidOnce` violated |

Each action of StageConcurrency is cut at an `await` of the Python code: asyncio switches
tasks only there, so everything between two awaits is atomic in the model as in the run.
