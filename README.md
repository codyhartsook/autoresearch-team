# Autoresearch Team

Collective intelligence layer for autonomous ML research. N parallel agents experiment, share findings, and converge faster than any solo agent.

Built on top of [autoresearch](https://github.com/karpathy/autoresearch) by @karpathy.

## The Idea

Autoresearch runs a single Claude Code agent in a loop: modify `train.py`, train for 5 minutes, keep improvements, discard failures, repeat. It works — Discussion #43 shows 126 experiments overnight, real improvements to val_bpb.

Autoresearch Team adds **collective intelligence**: N agents experimenting in parallel, sharing observations, replicating each other's results, and building on each other's branches. No synchronous rounds, no central orchestrator, no designated reviewer — agents read and write to a shared store on their own cadence, and collective behavior emerges from simple interaction rules.

The hypothesis: a team of agents that gossip, differentiate into niches, validate each other's claims, and fork promising lines of inquiry will converge faster than N independent agents or one agent running N times longer.

## Architecture

Three layers, each decoupled from the others:

```
PROTOCOL        — what the collective does (schemas, behaviors, interaction rules)
IMPLEMENTATION  — how a specific agent executes it (Claude Code sub-agents, etc.)
INFRASTRUCTURE  — where sessions run (Lightning AI, local GPU, Slurm)
```

### Coordination model: peer-to-peer

Every agent runs the same loop — experiment, publish, read, adapt. Coordination is fully decentralized: all communication happens through a shared knowledge store (append-only JSONL files + git branches). No message queues, no orchestrator, no barriers.

```
┌────────┐   reads/writes    ┌────────┐
│ Agent 0 │◄───────────────►│ Agent 1 │
└────┬───┘                   └───┬────┘
     │    ┌──────────────────┐   │
     ├───►│   Shared Store   │◄──┤
     │    │  (append-only    │   │
     │    │   JSONL files)   │   │
     │    └──────────────────┘   │
┌────┴───┐                  ┌───┴────┐
│ Agent 2 │◄──────────────►│ Agent 3 │
└────────┘   reads/writes   └────────┘
```

Each agent's loop:
1. **Read** shared store — recent results, observations, contradictions, activity by category
2. **Plan** — pick a direction (niche differentiation), pick a starting point (own branch or fork another's)
3. **Experiment** — modify `train.py`, commit, train, evaluate, keep/discard. Repeat for a batch.
4. **Publish** — write results and observations to shared store, push git branch
5. **GOTO 1**

No agent is special. Synthesis is distributed — every agent reads, interprets, and acts on the shared store. Human-readable summaries are a formatting task, not an agent role.

See [architecture.md](architecture.md) for the full system design with data flow, sub-agent hierarchy, scheduling model, and nomenclature.

## Collaborative Protocols

Six composable interaction protocols inspired by how real research communities work — publication, replication, citation, and gossip rather than top-down coordination:

| Protocol | What it does | Inspired by |
|----------|-------------|-------------|
| **Gossip** | Agents publish observations ("X hurts at depth>12"). Others read and incorporate during planning. | Researchers posting findings in Slack |
| **Niche Differentiation** | Agents prefer under-explored directions, creating diversity without explicit coordination. | Researchers naturally avoiding crowded topics |
| **Replication** | Agents independently verify each other's best results. Trust emerges from data, not self-reporting. | Peer review / replication studies |
| **Lineage Forking** | Agents adopt another's branch when its trajectory looks promising, creating a phylogenetic tree of research. | Building on prior work / citation |
| **Contradiction Detection** | Agents flag when their results conflict with another's observations. Contradictions are high-signal events. | Scientific debate / adversarial collaboration |
| **Adoption Rituals** | Agents explicitly track which results they build on, producing a citation/impact graph. | Citation networks |

These compose incrementally. The minimal viable stack is **Gossip + Niche Differentiation**. Replication, forking, contradictions, and adoption layer on as the system matures.

See [collaborative_protocols.md](research-docs/collaborative_protocols.md) for schemas, agent behaviors, tuning knobs, tradeoffs, and composition patterns for each protocol.

## Project Status

### Completed

**Research & design**
- Researched core autoresearch repo, inspiration discussion, and design space
- Explored experiment tracking options (git, W&B, MLflow, Lightning AI)
- Explored context tagging, discussion/feedback mechanisms, compute infrastructure
- Identified limitations of centralized orchestration; designed decentralized alternative
- Researched Claude Code capabilities: sub-agents, scheduled tasks (`/loop`), persistent memory
- Evaluated Beads (distributed graph issue tracker) as potential coordination layer
- Defined three-layer architecture: protocol / implementation / infrastructure
- Explored peer-to-peer collaborative protocols: gossip, replication, lineage forking, niche differentiation, contradiction detection, adoption rituals

**Infrastructure layer (Lightning AI)**
- CLI tool (`art`) for fleet management: init, launch, health, logs, teardown
- Session-based config (YAML) for launching arbitrary groups of Studios on any GPU type
- Idempotent studio setup: clones repos, installs dependencies via `uv`, optionally installs Claude CLI
- Telemetry: pulls `metrics.jsonl` from running Studios
- E2E tests: studio lifecycle, git coordination across Studios (push from A, fetch from B), run script execution

### Active — Protocol Design

Designing the collaborative protocol layer — the schemas, behaviors, and interaction rules that define how agents coordinate.

Open questions:
- Which protocol composition to start with (likely Gossip + Niche Differentiation)
- Observation quality: how to ensure agents write useful observations, not noise
- Replication variance: what's the noise floor on val_bpb from 5-minute runs?
- Git concurrency: strategy for multiple agents appending to shared JSONL files
- Context management: sub-agents for reading the shared store during planning

### Next

- Define protocol schemas (results, observations, replications, adoptions, contradictions)
- Implement the minimal viable agent loop (experiment → publish → read → plan → repeat)
- Build local infrastructure: launch script for tmux-based multi-session testing
- Test: 2-3 agents with Gossip + Niche Differentiation on a shared repo
- Measure val_bpb variance to calibrate replication thresholds

## Research Documents

| Document | Contents |
|----------|----------|
| [architecture.md](architecture.md) | System design — layers, roles, data flow, sub-agents, scheduling, nomenclature, alternatives considered |
| [collaborative_protocols.md](research-docs/collaborative_protocols.md) | Protocol design space — gossip, replication, lineage forking, niche differentiation, contradiction detection, adoption rituals, composition patterns, shared store layout |
| [research_and_plan.md](research-docs/research_and_plan.md) | Initial research — tracking options, context tagging, committee design, Lightning AI, modularity, original build plan |
| [decentralized_architecture.md](research-docs/decentralized_architecture.md) | Why decentralized beats centralized, shared knowledge store design, claims mechanism, periodic reviewer, `/loop` + skills patterns |
| [claude-sub-agents.md](research-docs/claude-sub-agents.md) | Claude Code sub-agents — capabilities, configuration, context isolation, persistent memory, tool restrictions |
| [next_step_discussion.md](research-docs/next_step_discussion.md) | Karpathy's vision — "asynchronously massively collaborative" research, SETI@home for ML |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Coordination model | Peer-to-peer (shared blackboard, no designated reviewer) | No hub bottleneck, no single point of interpretive failure, synthesis is distributed across all agents |
| Interaction rules | Composable protocols (gossip, replication, niche differentiation, etc.) | Simple local rules produce emergent collective behavior — closer to how real research communities work |
| Tracking | Git-primary (append-only JSONL + branches) | Zero dependencies, no write conflicts, full history, any tool can read (`cat`, `jq`, `grep`) |
| Context management | Sub-agents for shared store reading | Main agent stays focused on experiments; a sub-agent with fresh context reads the store and returns a compact planning summary |
| Scheduling | Claude Code `/loop` + cron | Built-in, zero-infrastructure periodic triggers; fires during training idle time |
| Agent coupling | Protocol is agent-agnostic; implementation is Claude Code first | Protocol (schemas + behaviors) is portable; Claude Code is the first implementation, not a hard dependency |
| Role structure | Uniform peers (no runner/reviewer split) | Every agent experiments, publishes, reads, and adapts. Specialization emerges from niche differentiation, not assignment. |
| Validation | Replication-based (agents verify each other) | Results are socially validated, not self-reported. Trust emerges from data. |

## References

- [autoresearch](https://github.com/karpathy/autoresearch) — the core single-agent ML research loop
- [autoresearch Discussion #43](https://github.com/karpathy/autoresearch/discussions/43) — example session report (126 experiments)
- [autoresearch PR #44](https://github.com/karpathy/autoresearch/pull/44) — example experiment branch
- [next_step_discussion.md](research-docs/next_step_discussion.md) — Karpathy's vision for collaborative research
