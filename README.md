# Autoresearch Team

Collective intelligence layer for autonomous ML research. N parallel agents experiment, share findings, and converge faster than any solo agent.

Built on top of [autoresearch](https://github.com/karpathy/autoresearch) by @karpathy.

## The Idea

Autoresearch runs a single Claude Code agent in a loop: modify `train.py`, train for 5 minutes, keep improvements, discard failures, repeat. It works — Discussion #43 shows 126 experiments overnight, real improvements to val_bpb.

Autoresearch Team adds **collective intelligence**: N runners experimenting in parallel, a reviewer synthesizing findings across all of them, and a shared knowledge store that lets agents learn from each other continuously. No synchronous rounds, no central orchestrator — agents read and write to shared state on their own cadence.

The hypothesis: a team of agents that share insights, avoid each other's dead ends, and build on each other's discoveries will converge faster than N independent agents or one agent running N times longer.

## Architecture

Three layers, each decoupled from the others:

```
PROTOCOL        — what the collective does (schemas, behaviors, scheduling)
IMPLEMENTATION  — how a specific agent executes it (Claude Code sub-agents, etc.)
INFRASTRUCTURE  — where sessions run (local GPU, Lightning AI, Slurm)
```

Three roles:

- **Runner** (N instances, GPU) — runs the autoresearch experiment loop, writes manifests and results, reads shared state to adapt
- **Reviewer** (1 instance, CPU) — periodically synthesizes results across all runners, updates leaderboard and insights
- **Human** (async) — reads published reviews, optionally injects directives

Coordination is decentralized. All communication happens through a shared knowledge store (JSONL files + git branches). No message queues, no orchestrator, no barriers. Runners and the reviewer operate on independent cadences.

See [architecture.md](architecture.md) for the full system design, data flow, sub-agent hierarchy, scheduling model, and nomenclature.

## Project Status

**Phase: Research & Design** — architecture defined, implementation not yet started.

### Completed

- Researched core autoresearch repo, inspiration discussion, and design space
- Explored experiment tracking options (git, W&B, MLflow, Lightning AI)
- Explored context tagging, discussion/feedback mechanisms, compute infrastructure
- Identified limitations of centralized orchestration; designed decentralized alternative
- Researched Claude Code capabilities: sub-agents, scheduled tasks (`/loop`), persistent memory
- Evaluated Beads (distributed graph issue tracker) as potential coordination layer
- Defined three-layer architecture: protocol / implementation / infrastructure
- Defined roles, shared knowledge store, data flow, sub-agent hierarchy, scheduling model

### Next

- Define the protocol: schemas, behaviors, and scheduling rules (agent-agnostic spec)
- Implement in Claude Code: sub-agent definitions, program.md, loop configuration
- Build local infrastructure: launch script for tmux-based multi-session runs
- Test: single enhanced runner producing manifests, then multi-runner with reviewer

## Research Documents

| Document | Contents |
|----------|----------|
| [architecture.md](architecture.md) | System design — layers, roles, data flow, sub-agents, scheduling, nomenclature, alternatives considered |
| [research_and_plan.md](research-docs/research_and_plan.md) | Initial research — tracking options, context tagging, committee design, Lightning AI, modularity, missed questions, original build plan |
| [decentralized_architecture.md](research-docs/decentralized_architecture.md) | Why decentralized beats centralized, shared knowledge store design, claims mechanism, periodic reviewer, `/loop` + skills patterns, revised build plan |
| [claude-sub-agents.md](research-docs/claude-sub-agents.md) | Claude Code sub-agents documentation — capabilities, configuration, context isolation, persistent memory, tool restrictions |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Coordination model | Decentralized (shared blackboard) | No synchronous barriers, no single point of failure, fault-tolerant, scales naturally |
| Tracking | Git-primary (JSONL files + branches) | Zero dependencies, compatible with upstream autoresearch, any agent can read/write |
| Context management | Sub-agents with isolated context windows | Runners stay focused on experiments; analysis happens in disposable sub-agents that return compact summaries |
| Scheduling | Claude Code `/loop` + cron | Built-in, zero-infrastructure periodic triggers; fires during training idle time |
| Agent coupling | Protocol is agent-agnostic; implementation is Claude Code first | Protocol (schemas + behaviors) is portable; Claude Code sub-agents are the first implementation, not a hard dependency |
| Round structure | None (continuous async) | Agents run, publish, read, adapt on their own cadence; reviewer synthesizes periodically without blocking anyone |

## References

- [autoresearch](https://github.com/karpathy/autoresearch) — the core single-agent ML research loop
- [autoresearch Discussion #43](https://github.com/karpathy/autoresearch/discussions/43) — example session report (126 experiments)
- [autoresearch PR #44](https://github.com/karpathy/autoresearch/pull/44) — example experiment branch
- [next_step_discussion.md](research-docs/next_step_discussion.md) — Karpathy's vision for collaborative research
