# Decentralized Architecture — Findings & Revised Thinking

Builds on `research_and_plan.md`. Captures the conclusions from exploring decentralization, agent roles, and Claude Code scheduled tasks as coordination primitives.

---

## 1. Why the Centralized Design Doesn't Scale

The original `research_and_plan.md` proposes a single orchestrator running synchronous rounds:

```
Orchestrator launches N runners → waits for ALL to finish →
  runs aggregation → runs committee → runs planner →
    distributes directives → launches next round
```

This is a **barrier-based** design. Problems emerge at scale:

| Problem | Impact |
|---------|--------|
| **Synchronous barriers** | Fastest agent idles waiting for slowest. With 3 agents, minor. With 20, could waste 30+ min of GPU time per round. |
| **Single point of failure** | Orchestrator crashes → entire system stops. No partial progress preserved. |
| **Committee bottleneck** | One committee reviews ALL results. At 20 agents × 12 experiments = 240 manifests — context window explodes. |
| **Rigid round boundaries** | An agent that discovers something huge at experiment #3 has to wait until the round ends for anyone to benefit. |
| **Linear review cost** | Committee work grows O(N) with agents. Eventually committee phase dominates wall time. |

### The Karpathy vision is async, not synchronous

The `next_step_discussion.md` describes "asynchronously massively collaborative" research. That word **asynchronous** is critical. It implies agents on their own timelines, occasionally reading each other's work — not marching in lockstep rounds.

Real research labs work this way too:
- Researchers don't wait for everyone to finish before discussing
- Someone posts a result in Slack, others read it when they can
- Ideas spread through **gossip**, not central coordination
- The best ideas get picked up organically — no one "assigns" them

---

## 2. Decentralized Model

### Core idea: shared knowledge store replaces the orchestrator

```
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Agent 0 │  │ Agent 1 │  │ Agent 2 │  │ Agent 3 │
│         │  │         │  │         │  │         │
│ run exp │  │ run exp │  │ run exp │  │ run exp │
│ publish │  │ publish │  │ publish │  │ publish │
│ read    │  │ read    │  │ read    │  │ read    │
│ adapt   │  │ adapt   │  │ adapt   │  │ adapt   │
│ repeat  │  │ repeat  │  │ repeat  │  │ repeat  │
└────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
     │            │            │            │
     ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────┐
│            Shared Knowledge Store               │
│  (git branches, manifests, leaderboard.jsonl,   │
│   dead_ends.jsonl, insights.jsonl, claims/)     │
└─────────────────────────────────────────────────┘
```

Each agent is autonomous and runs its own loop:

```
AGENT LOOP (no orchestrator):
  1. Read shared state (leaderboard, dead ends, recent insights)
  2. Self-plan: pick what to explore based on what others have found
  3. Run K experiments (small batch, 3-5 not 12)
  4. Publish results to shared store (push branch, append to leaderboard)
  5. GOTO 1
```

**No rounds. No barriers. No central coordinator.**

### Shared knowledge store artifacts

Instead of a coordinator telling agents what to do, agents read and write to shared state:

| Artifact | Purpose | Written by | Read by |
|----------|---------|------------|---------|
| `leaderboard.jsonl` | Global ranking of best configs with commit refs | Any agent after an experiment | All agents before planning |
| `dead_ends.jsonl` | Known bad directions with evidence | Any agent after a discard | All agents before planning |
| `insights.jsonl` | Observations, patterns, hypotheses, synthesis | Any agent or the reviewer | All agents before planning |
| `claims/{agent_id}.json` | "I'm exploring X" — prevents duplication | Agent before starting a batch | All agents before planning |
| Git branches | Actual code + results + manifests | Each agent on its own branch | Any agent that wants to cherry-pick |

This is a **shared blackboard architecture** — a classic pattern in distributed AI systems.

### Claims mechanism: lightweight decentralized coordination

The claims system prevents N agents from all trying the same thing:

```python
# Agent self-planning (before each batch of experiments)
def plan_next_batch(shared_store):
    leaderboard = read_jsonl("data/leaderboard.jsonl")
    dead_ends = read_jsonl("data/dead_ends.jsonl")
    active_claims = read_claims("data/claims/")
    recent_insights = read_jsonl("data/insights.jsonl")

    # Pick starting config (not always the best — sometimes pick diverse)
    if random() < 0.2:
        start_from = pick_diverse_config(leaderboard)
    else:
        start_from = leaderboard.best()

    # Pick exploration direction (avoid what others are doing)
    taken_categories = {c.category for c in active_claims if not c.expired()}
    available = ALL_CATEGORIES - taken_categories - dead_ends
    my_focus = pick_from(available, weighted_by=recent_insights)

    # Publish claim (with TTL so it expires if agent crashes)
    publish_claim(my_agent_id, my_focus, ttl_minutes=30)

    return start_from, my_focus
```

Claims have a **TTL**. If an agent crashes, its claim expires and the direction becomes available again. No cleanup needed.

---

## 3. Who Does the Committee's Job?

Three options explored, with recommendation:

### Option A: Every agent is its own mini-committee

Each agent, after every K experiments, reads the shared store and does a self-review. It re-ranks, updates its own understanding, pivots if something better was found.

- **Pro:** Simplest. No coordination overhead. Scales linearly.
- **Con:** Each agent has a narrower view. No "synthesis across all agents" moment. Agents might miss cross-cutting patterns.

### Option B: Periodic lightweight reviewer (non-blocking) ← Recommended

A dedicated Claude Code session (on CPU, no GPU needed) periodically reads all recent results and publishes synthesis. **Agents don't wait for it** — they just read whatever synthesis exists when they start their next batch.

```
REVIEWER (runs on its own cadence, e.g., every 20 minutes):
  1. Read all new results since last review
  2. Update leaderboard rankings
  3. Identify convergent/divergent findings
  4. Publish synthesis to insights.jsonl
  5. Sleep until next cycle
```

- **Pro:** You get deep synthesis without blocking anyone. Scales well.
- **Con:** Agents may act on slightly stale synthesis. But this is fine — real researchers do too.

### Option C: Quorum-based review

When M out of N agents have published new results, a review triggers. Rolling committee.

- **Pro:** Adapts to agent pace naturally.
- **Con:** More complex coordination logic.

**Recommendation: Option B.** Simplest path to decentralization. The reviewer is a **service**, not a bottleneck. Agents benefit from its output but never block on it.

---

## 4. Claude Code Scheduled Tasks as Coordination Primitive

### The capability

Claude Code has built-in **session-scoped cron scheduling** via `/loop` and the `CronCreate` tool. Key properties:

- Scheduled prompts have **full tool access** (file I/O, bash, git, API calls)
- `/loop` can invoke **custom skills** (e.g., `/loop 20m /synthesize-results`)
- Fires **between turns** when the session is idle — won't interrupt an active experiment
- Standard 5-field cron expressions, local timezone
- Up to 50 scheduled tasks per session
- 3-day auto-expiry for recurring tasks (sufficient for overnight runs)

### Why this matters

Scheduled tasks turn Claude Code sessions into **self-managing autonomous agents**. No external orchestrator needed — each session manages its own review/adaptation cycle via cron loops.

### Pattern 1: The Periodic Reviewer

A long-running Claude Code session on a cheap CPU instance. This IS the reviewer:

```
/loop 20m /synthesize-results
/loop 30m /publish-review
```

Every 20 minutes, Claude wakes up, reads all git branches, parses new manifests, updates the leaderboard, identifies patterns, writes insights. Every 30 minutes, it publishes a human-readable summary to GitHub Discussions.

No orchestrator. No custom Python service. One Claude Code session with two loop commands.

### Pattern 2: Agent self-adaptation

Each experiment runner (on a GPU) schedules its own monitoring:

```
/loop 15m /check-shared-state
```

The `/check-shared-state` skill reads `leaderboard.jsonl` and `insights.jsonl`, checks if another agent found something significantly better, and if so updates the agent's exploration strategy. The agent keeps running experiments but periodically glances at the shared store and pivots.

This turns "wait for round to end, receive directive" into **continuous, self-directed adaptation**.

### Pattern 3: Dead-end propagation

```
/loop 10m /check-dead-ends
```

Checks `dead_ends.jsonl` for new entries. If the agent is currently exploring a direction marked dead by another agent, it abandons and picks a new direction. Within 10 minutes, every agent knows what doesn't work.

### Pattern 4: Human oversight without rigid checkpoints

```
/loop 30m /check-human-directives
```

Checks if a human has written to `data/human_directive.json`. If so, propagates it to `insights.jsonl` with `priority: high` so all agents pick it up on their next read cycle.

Humans steer by dropping a file. The loop picks it up. No round boundaries needed.

### The skill + loop architecture

The entire system reduces to **a set of skills** and **a set of loop schedules**:

| Skill | What it does |
|-------|-------------|
| `/synthesize-results` | Reads all branches, aggregates manifests, updates leaderboard, writes insights |
| `/check-dead-ends` | Scans for newly dead-ended directions, updates shared state |
| `/publish-review` | Produces a human-readable "state of research" summary, posts to GitHub Discussion |
| `/claim-direction` | Reads claims, picks an unclaimed direction, publishes claim |
| `/check-shared-state` | Reads leaderboard + insights, adapts exploration strategy if landscape changed |
| `/check-human-directives` | Reads human directive file, propagates to shared store |

System deployment becomes:

```bash
# Reviewer session (CPU, long-running):
#   /loop 20m /synthesize-results
#   /loop 30m /publish-review
#   /loop 30m /check-human-directives

# Each experiment runner session (GPU):
#   /loop 10m /check-dead-ends
#   /loop 15m /check-shared-state
#   (main loop: run experiments, write manifests, push to git)
```

### Scheduled task limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **Session-scoped, 3-day expiry** | Can't run indefinitely. Overnight runs (8-12 hours) fine. Multi-day needs restarts. | Acceptable for Phase 0-3. Move to GitHub Actions or Desktop scheduled tasks for durability in Phase 4+. |
| **Only fires when idle** | Won't fire during active training (long bash command). | Actually desirable — don't interrupt training. Fires in the natural gap between experiments. |
| **No catch-up for missed fires** | If synthesis takes 10min and loop is 10min, might skip a cycle. | Set intervals wider than expected execution time (20min loop for 5min task). |
| **50 task limit per session** | — | Non-issue. 5-6 loops per session is plenty. |

### Upgrade path for production

For production/multi-day campaigns:

- **GitHub Actions with `schedule` trigger**: Durable cron that survives restarts, runs headless. The reviewer role is a natural fit.
- **Desktop scheduled tasks**: GUI-configured durable scheduling for local setups.
- `/loop` remains ideal for **prototyping** and **single-session overnight runs**.

---

## 5. Failure Handling Becomes Trivial

A major advantage of decentralization:

| Failure | Centralized impact | Decentralized impact |
|---------|-------------------|---------------------|
| Agent crashes mid-run | Orchestrator must detect, potentially stalls round | Other agents don't notice. Crashed agent's claims expire via TTL. Someone else picks up the direction. |
| GPU OOM kills training | Round incomplete, all agents wait | That agent retries or skips. No one else affected. |
| Bad insight published | Committee might propagate it to all agents via directives | Other agents quickly produce contradicting evidence. Leaderboard self-corrects. |
| Reviewer crashes | — | Agents keep running. They just use stale synthesis until reviewer restarts. No data loss. |
| Git conflict | Central merge step fails | Agents work on isolated branches. No conflicts possible. Cherry-picking is optional. |

---

## 6. What You Lose (Tradeoffs)

1. **Weaker synthesis.** A dedicated committee reading ALL results at once can spot cross-cutting patterns that individual agents miss. The periodic reviewer partially addresses this but it's not as deep as a synchronous committee with full context.

2. **Potential for redundant work.** Claims help, but two agents might still independently try similar things. Some waste is the cost of eliminating coordination overhead.

3. **Harder to debug.** No clean round boundaries means the history is a continuous stream, not discrete chapters. Harder to say "in round 3, the committee decided X."

4. **Looser convergence on best config.** Agents may work off slightly stale "best" configs. This could actually be a feature (diversity) but could also mean slower convergence.

---

## 7. Recommended Hybrid Architecture

Decentralized agents with a lightweight central pulse:

```
DECENTRALIZED AGENTS (continuous, async, on GPUs)
  ├── Each is a Claude Code session with the autoresearch loop
  ├── Read/write shared knowledge store (git + JSONL files)
  ├── Self-plan using claims mechanism
  ├── Run experiments in small batches (3-5)
  ├── /loop 10m /check-dead-ends
  └── /loop 15m /check-shared-state

PERIODIC REVIEWER (background, non-blocking, on CPU)
  ├── Claude Code session with no experiment duties
  ├── /loop 20m /synthesize-results
  ├── /loop 30m /publish-review
  └── /loop 30m /check-human-directives

HUMAN OVERSIGHT (async, manual trigger)
  ├── Reads published reviews in GitHub Discussions
  ├── Drops directives into data/human_directive.json
  └── Agents pick them up naturally on next read cycle
```

```
┌─────────────────────────────────────────────────────────────┐
│                     Human (async)                           │
│  reads Discussions, writes human_directive.json             │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────▼──────────────┐
              │   Periodic Reviewer (CPU) │
              │   /loop /synthesize       │
              │   /loop /publish-review   │
              │   /loop /check-human      │
              └────────────┬──────────────┘
                           │ reads/writes
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Shared Knowledge Store                     │
│  leaderboard.jsonl │ dead_ends.jsonl │ insights.jsonl       │
│  claims/           │ human_directive.json                   │
│  git branches (per agent, experiment manifests, results)    │
└───┬──────────────┬──────────────┬──────────────┬────────────┘
    │              │              │              │
    ▼              ▼              ▼              ▼
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│Agent 0 │   │Agent 1 │   │Agent 2 │   │Agent 3 │
│  H100  │   │  H100  │   │  H100  │   │  H100  │
│/loop   │   │/loop   │   │/loop   │   │/loop   │
│ checks │   │ checks │   │ checks │   │ checks │
└────────┘   └────────┘   └────────┘   └────────┘
```

---

## 8. Impact on the Build Plan

The original 6-phase plan from `research_and_plan.md` adapts as follows:

| Original Phase | Revised Phase | What changes |
|---------------|--------------|-------------|
| **Phase 0: Foundation** | **Phase 0: Foundation** | Same — schemas, manifest format, experiment wrapper, enhanced program.md. No change needed. |
| **Phase 1: Tracking** | **Phase 1: Shared Store** | Reframe from "tracking infrastructure" to "shared knowledge store." Build the JSONL-based leaderboard, dead_ends, insights, and claims formats. Git tracker stays. Drop W&B from initial scope (add later if needed). |
| **Phase 2: Collective Intelligence** | **Phase 2: Skills** | Instead of building `committee.py` as a standalone Claude API script, build **Claude Code skills**: `/synthesize-results`, `/check-dead-ends`, `/publish-review`, `/claim-direction`, `/check-shared-state`, `/check-human-directives`. The committee logic lives inside skills, not a bespoke service. |
| **Phase 3: Orchestration** | **Phase 3: Launch & Loop** | Replace `orchestrator.py` with a **launch script** that starts N Claude Code sessions with the right `/loop` commands. No synchronous round management. Test a 3-agent decentralized run locally. |
| **Phase 4: Lightning AI** | **Phase 4: Lightning AI** | Lightning launches the sessions on GPUs. Each session self-manages via loops. Shared filesystem maps to the knowledge store. Pipeline definition becomes simpler — just "start N sessions." |
| **Phase 5: Polish** | **Phase 5: Polish & Durability** | Same items (convergence detection, explore/exploit, cost tracking). Add: migrate reviewer to GitHub Actions for durable scheduling. Add: Pareto front of configs instead of single-best starting point. |

### Key simplification

The orchestration layer largely **disappears**. It's replaced by:
1. A launch script (start sessions)
2. A set of skills (the shared vocabulary)
3. A set of loop schedules (the coordination rhythm)
4. A shared file store (the coordination substrate)

The collective intelligence layer becomes **skills + JSONL files**, not a bespoke framework.

---

## 9. Open Questions (Carried Forward + New)

### From original plan (still relevant)
1. **Agent framework**: Claude Code CLI sessions vs. Anthropic Python API for runners? CLI is simpler and gets `/loop` for free. API gives tighter control but loses scheduling.
2. **Number of agents**: Start with 3. The decentralized design scales more gracefully than the centralized one, so this is less critical to get right upfront.
3. **W&B integration**: Deferred. Start git-only + JSONL. Add W&B when/if the JSONL approach proves insufficient for visualization.

### New questions from decentralization
4. **Shared store concurrency**: Multiple agents writing to `leaderboard.jsonl` simultaneously. Use append-only JSONL (no conflicts) + periodic compaction by the reviewer? Or use git as the merge mechanism?
5. **Claims granularity**: What categories do we use? Too coarse (e.g., "architecture") and agents still overlap. Too fine (e.g., "attention_heads_8_to_12") and the category space is too large to enumerate.
6. **Reviewer context window**: Even with periodic synthesis, the reviewer reading ALL manifests across ALL agents may eventually overflow context. Build in summarization or windowed reads (only last N hours)?
7. **How to launch N Claude Code sessions programmatically**: Need a script that starts N terminal sessions, each with the right initial prompt and `/loop` commands. Possible via `tmux` + `claude` CLI? Lightning Studio API?
