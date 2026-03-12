# Autoresearch Team — Architecture

## System Layers

```
┌─────────────────────────────────────────────────────────────┐
│                        PROTOCOL                             │
│                                                             │
│  Agent-agnostic. Defines what the collective intelligence   │
│  does: the shared language (schemas), the behaviors each    │
│  role performs, and the timing rules for coordination.      │
│                                                             │
│  Portable across any agent framework or LLM.                │
├─────────────────────────────────────────────────────────────┤
│                     IMPLEMENTATION                          │
│                                                             │
│  Agent-specific. How a given agent framework executes the   │
│  protocol: sub-agents, skills, program files, scheduling    │
│  mechanisms. One implementation per supported framework.    │
│                                                             │
│  First target: Claude Code. Future: Codex, raw API, etc.    │
├─────────────────────────────────────────────────────────────┤
│                     INFRASTRUCTURE                          │
│                                                             │
│  Platform-specific. Where sessions run, how they're         │
│  launched, shared storage, GPU provisioning, cost controls. │
│  Pure plumbing — no intelligence logic.                     │
│                                                             │
│  First target: local (tmux). Future: Lightning AI, Slurm.   │
└─────────────────────────────────────────────────────────────┘
```

Each layer depends only on the one above it. The protocol doesn't know which agent runs it. The implementation doesn't know which platform hosts it.

---

## Roles

The system has three roles. Each role is a long-running session.

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   RUNNER (N instances)                                       │
│                                                              │
│   The experiment engine. Runs the autoresearch loop:         │
│   modify train.py → commit → train → evaluate → keep/discard │
│                                                              │
│   Writes: manifests, results, branches, claims               │
│   Reads:  shared store (leaderboard, dead ends, insights)    │
│   Runs on: GPU (H100/A100)                                   │
│   Spawns:  analyst sub-agents for context-isolated reading   │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   REVIEWER (1 instance)                                      │
│                                                              │
│   The synthesis engine. Periodically reads all experiment    │
│   results across all runners, identifies patterns, ranks     │
│   experiments, and publishes insights.                       │
│                                                              │
│   Writes: leaderboard, insights, published reviews           │
│   Reads:  all runner branches, manifests, results            │
│   Runs on: CPU                                               │
│   Spawns:  analyst sub-agents for heavy cross-agent reading  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   HUMAN (async, external)                                    │
│                                                              │
│   Reads published reviews. Optionally injects directives.    │
│   Not a managed session — just a person reading/writing      │
│   files or GitHub Discussions.                               │
│                                                              │
│   Writes: human directives                                   │
│   Reads:  published reviews, leaderboard                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Shared Knowledge Store

All coordination happens through files on a shared filesystem. No message passing, no queues, no databases. Agents read and write files.

```
data/
├── leaderboard.jsonl          # Ranked experiment results across all runners
├── dead_ends.jsonl            # Directions proven unproductive
├── insights.jsonl             # Synthesized findings and patterns
├── claims/                    # What each runner is currently exploring
│   ├── runner-0.json
│   ├── runner-1.json
│   └── runner-2.json
├── human_directive.json       # Optional steering from human
└── rounds/                    # Per-batch artifacts
    └── {runner-id}/
        ├── results.tsv        # Experiment log for this runner
        ├── session_report.json
        └── manifests/         # Per-experiment context
            ├── exp-001.json
            ├── exp-002.json
            └── ...
```

Git branches serve as the code-level source of truth. Each runner works on its own branch. The shared knowledge store (`data/`) is the coordination substrate.

---

## Data Flow

```
RUNNER                          SHARED STORE                    REVIEWER
──────                          ────────────                    ────────

  ┌─ read ─────────────────────── leaderboard.jsonl
  │                                dead_ends.jsonl
  │                                insights.jsonl
  │                                claims/
  │
  │  (self-plan: pick direction,
  │   pick starting config,
  │   publish claim)
  │
  ├─ write ────────────────────── claims/runner-{id}.json
  │
  │  (run K experiments:
  │   edit train.py, commit,
  │   train, evaluate, keep/discard)
  │
  ├─ write ────────────────────── manifests/exp-{n}.json
  │                                results.tsv
  │                                git branch
  │
  │                                                     read ──┐
  │                                leaderboard.jsonl ◄─────────┤
  │                                insights.jsonl ◄────────────┤
  │                                dead_ends.jsonl ◄───────────┤
  │                                                            │
  │                              (synthesize: rank experiments,│
  │                               identify patterns, detect    │
  │                               convergence, flag dead ends) │
  │                                                            │
  │                                leaderboard.jsonl ──write──►│
  │                                insights.jsonl ─────write──►│
  │                                dead_ends.jsonl ────write──►│
  │                                published review ───write──►│
  │
  │  (next batch: read updated
  │   shared store, adapt)
  │
  ┌─ read ─────────────────────── leaderboard.jsonl (updated)
  │                                insights.jsonl (updated)
  │                                dead_ends.jsonl (updated)
  v
  ... continues ...
```

There are no rounds or barriers. Runners and the reviewer operate on their own cadences. Runners consume whatever state exists in the shared store at the time they read it.

---

## Sub-Agents (within a session)

Each role (runner, reviewer) is a **main agent** that spawns **sub-agents** for context-isolated work. Sub-agents get a fresh context window, do their job, and return a compact result. The main agent's context stays clean.

```
RUNNER (main agent)
│
│  Main context: train.py, current experiment, program.md
│
├──► Analyst sub-agent (read-only, fresh context)
│    "Read leaderboard.jsonl + insights.jsonl + dead_ends.jsonl.
│     Return JSON: {best_config, new_dead_ends, should_pivot, reason}"
│    ← returns ~500 tokens
│
├──► Planner sub-agent (read-only, fresh context)
│    "Read my last 5 manifests. Analyze my trajectory.
│     Suggest next experiment. Return JSON."
│    ← returns ~300 tokens
│
│  Main agent absorbs compact summaries, continues experiment loop


REVIEWER (main agent)
│
│  Main context: lightweight — mostly scheduling and coordination
│
├──► Aggregator sub-agent (read-only, fresh context)
│    "Read all manifests and results.tsv across all runners.
│     Produce ranked experiment list + convergent findings."
│    ← returns structured JSON
│
├──► Synthesizer sub-agent (read/write, fresh context, persistent memory)
│    "Given aggregated data, produce insights, update leaderboard,
│     flag dead ends. Consult your memory for prior patterns."
│    ← writes to shared store, returns summary
│
├──► Publisher sub-agent (read/write, fresh context)
│    "Produce human-readable review. Post to GitHub Discussion."
│    ← returns confirmation
```

Sub-agents cannot spawn other sub-agents (flat hierarchy). The main agent is always the coordinator within a session.

---

## Scheduling

Scheduling determines when sub-agents fire within each role. Timing is independent per role — no cross-role synchronization.

```
RUNNER SESSION
│
│  Main loop (continuous):
│    edit → commit → train (5 min) → evaluate → keep/discard → repeat
│
│  Scheduled (fires during idle gaps between experiments):
│    every ~15 min:  spawn analyst sub-agent → read shared store → adapt
│    every ~10 min:  spawn dead-end checker → avoid wasted experiments
│    every ~K experiments: spawn planner sub-agent → reassess trajectory


REVIEWER SESSION
│
│  No main loop. Entirely schedule-driven.
│
│  every ~20 min:  spawn aggregator → read all results → rank
│  every ~20 min:  spawn synthesizer → produce insights → update store
│  every ~30 min:  spawn publisher → post review to GitHub Discussion
│  every ~30 min:  check human_directive.json → propagate if present
```

---

## Protocol → Implementation → Infrastructure

### Protocol (this repo, `protocol/`)

Defines the system in agent-agnostic terms:

```
protocol/
├── schemas/                       # Shared data formats
│   ├── manifest.schema.json       # Per-experiment context
│   ├── leaderboard.schema.json    # Global rankings
│   ├── dead_ends.schema.json      # Known bad directions
│   ├── insights.schema.json       # Synthesized findings
│   ├── claims.schema.json         # Exploration claims with TTL
│   ├── session_report.schema.json # Per-runner batch summary
│   └── human_directive.schema.json
│
├── behaviors/                     # What each role/sub-agent does
│   ├── runner.md                  # Core experiment loop + when to delegate
│   ├── analyst.md                 # Read shared store, return summary
│   ├── planner.md                 # Assess trajectory, suggest next move
│   ├── aggregator.md              # Cross-runner result aggregation
│   ├── synthesizer.md             # Pattern detection, insight generation
│   ├── publisher.md               # Human-readable review production
│   └── dead_end_checker.md        # Dead-end detection and propagation
│
└── scheduling.md                  # Timing rules per role
```

### Implementation (per agent framework, `implementations/`)

How the protocol executes in a specific agent:

```
implementations/
├── claude-code/
│   ├── agents/                    # Sub-agent definitions (.md files)
│   │   ├── analyst.md             # Implements protocol/behaviors/analyst.md
│   │   ├── planner.md
│   │   ├── aggregator.md
│   │   ├── synthesizer.md
│   │   ├── publisher.md
│   │   └── dead-end-checker.md
│   ├── program.md                 # Runner main loop instructions
│   └── reviewer-program.md        # Reviewer main loop instructions
│
└── (future: codex/, api/, etc.)
```

### Infrastructure (per platform, `infra/`)

How sessions are launched and where they run:

```
infra/
├── local/
│   └── launch.sh                  # tmux sessions on local GPU
├── lightning/
│   ├── launch.py                  # Lightning SDK: Studios/Jobs on H100s
│   ├── studio_setup.sh            # Environment provisioning
│   └── shared_storage.md          # How shared filesystem is configured
└── (future: slurm/, cloud-vms/, etc.)
```

---

## Considered Alternative: Beads (Distributed Graph Issue Tracker)

[Beads](https://github.com/steveyegge/beads) (`bd`) is a distributed, git-backed, Dolt-powered graph issue tracker designed for AI agents. It was evaluated as a potential replacement for the homegrown shared knowledge store.

### What Beads provides

- **Dolt database**: Version-controlled SQL with cell-level merge — eliminates concurrent write conflicts entirely
- **Hash-based IDs** (`bd-a1b2`): No merge collisions across agents, even on separate branches
- **Atomic claims**: `bd update <id> --claim` sets assignee + in_progress in one operation
- **Graph links**: `relates_to`, `duplicates`, `supersedes`, `replies_to` — richer than flat JSONL
- **Messaging**: `bd mail` with threading for agent-to-agent communication
- **Federation**: Peer-to-peer sync via Dolt remotes — could relax the shared filesystem requirement
- **Compaction**: Semantic "memory decay" summarizes old closed items to save context window
- **JSON output**: Every command supports `--json` — built for agent consumption

### Where it maps to our architecture

| Our concept | Beads equivalent | Fit |
|------------|-----------------|-----|
| **Claims** | `bd update <id> --claim` | Strong — atomic, conflict-free, proper database |
| **Dead ends** | `bd close <id> --reason "Dead end"` | Partial — dead ends aren't really "completed tasks" |
| **Insights / synthesis** | `bd mail` with threading | Interesting — richer than JSONL append, supports discussion chains |
| **Leaderboard progression** | `supersedes` links | Good — "config v2 supersedes config v1" is a natural chain |
| **Related experiments** | `relates_to` links | Useful — links experiments exploring the same direction |
| **Duplicate detection** | `duplicates` links | Useful — flags when two agents tried the same thing |

### Why not for the PoC

**Impedance mismatch.** Beads models discrete work items with lifecycles (`open → in_progress → closed`). Autoresearch models a continuous optimization loop with shared observations. Experiments aren't tasks — they're hypotheses tested and observations recorded. Shoehorning exploration directions into issue lifecycles creates friction without clear benefit.

**New dependency.** Beads requires Dolt (a version-controlled SQL database). The current design uses flat JSONL files that any agent can read/write with zero dependencies. For a PoC, the simplicity of `cat data/leaderboard.jsonl` is hard to beat.

**The 80/20 on claims.** Atomic claims with hash IDs is the strongest fit, but a JSON file with a TTL gets 80% of the value with 5% of the complexity for 3 agents.

### When to reconsider

- **Concurrency issues**: If multiple agents writing to JSONL simultaneously causes corruption or lost writes, Dolt's cell-level merge solves this definitively
- **Structured research tasks**: If the system evolves toward the trajectory planner creating discrete "research assignments" that get claimed, worked, and completed — that's exactly Beads' model
- **Federation over shared filesystem**: If the shared filesystem constraint becomes limiting (e.g., agents on different clouds), Beads' federation gives peer-to-peer sync without shared storage
- **Scale beyond ~5 agents**: At higher agent counts, the graph structure, deduplication, and atomic operations become more valuable than flat-file simplicity

### Potential incremental adoption path

Rather than all-or-nothing, Beads could be adopted for specific subsystems:

1. **Phase 0-3**: JSONL files (current plan, zero dependencies)
2. **If claims need hardening**: Adopt `bd` for claims only — `bd create` for directions, `bd update --claim` for atomic ownership, `bd close` for completion/dead-end
3. **If messaging is useful**: Add `bd mail` for reviewer ↔ runner communication alongside JSONL insights
4. **Full adoption**: Replace the entire shared knowledge store with Beads if the task-based model proves natural after iteration

---

## Nomenclature

| Term | Definition |
|------|-----------|
| **Protocol** | The agent-agnostic specification: schemas, behaviors, and scheduling rules. |
| **Implementation** | An agent-specific realization of the protocol (e.g., Claude Code sub-agents). |
| **Infrastructure** | Platform-specific compute provisioning and session management. |
| **Runner** | A role. Long-running session that executes the autoresearch experiment loop on a GPU. |
| **Reviewer** | A role. Long-running session that synthesizes results across runners on CPU. |
| **Human** | A role. External async observer who reads reviews and optionally injects directives. |
| **Sub-agent** | A short-lived, context-isolated worker spawned by a main agent within a session. |
| **Main agent** | The primary agent in a session (runner or reviewer) that coordinates sub-agent spawns. |
| **Shared knowledge store** | The set of files on shared storage that all sessions read/write for coordination. |
| **Manifest** | A JSON file describing one experiment: hypothesis, reasoning, category, results. |
| **Leaderboard** | Append-only JSONL ranking the best experiment configs across all runners. |
| **Dead ends** | JSONL of directions proven unproductive, with evidence. Agents avoid these. |
| **Insights** | JSONL of synthesized findings — patterns, convergent discoveries, strategic observations. |
| **Claim** | A JSON declaration that a runner is currently exploring a given direction. Has a TTL. |
| **Directive** | A JSON instruction from a human or the reviewer that influences runner behavior. |
| **Behavior** | A markdown spec describing what a role or sub-agent does, in agent-agnostic terms. |
| **Schedule** | The timing rules for when sub-agents fire within a role. |
| **Session** | A single long-running agent process (one runner or one reviewer). |
| **Batch** | A small group of experiments (3-5) a runner executes before checking shared state. |
