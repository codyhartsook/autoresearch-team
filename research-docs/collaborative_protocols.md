# Collaborative Protocols — Design Space Exploration

Reference document for peer-to-peer collaboration protocols that promote cross-experiment learning without prescribed roles. Each protocol is a composable building block — they can be adopted independently or layered together.

The guiding principle: **design interaction rules, not intelligence hierarchies. Let collective behavior emerge from simple local decisions.**

---

## Table of Contents

1. [Context & Motivation](#1-context--motivation)
2. [Protocol 1: Replication](#2-protocol-1-replication)
3. [Protocol 2: Lineage Forking](#3-protocol-2-lineage-forking)
4. [Protocol 3: Gossip (Observations)](#4-protocol-3-gossip-observations)
5. [Protocol 4: Niche Differentiation](#5-protocol-4-niche-differentiation)
6. [Protocol 5: Contradiction Detection](#6-protocol-5-contradiction-detection)
7. [Protocol 6: Adoption Rituals](#7-protocol-6-adoption-rituals)
8. [Comparison Matrix](#8-comparison-matrix)
9. [Composition Patterns](#9-composition-patterns)
10. [Role Model: Peers vs. Runner/Reviewer](#10-role-model-peers-vs-runnerreviewer)
11. [Shared Store Layout (Revised)](#11-shared-store-layout-revised)
12. [Open Questions](#12-open-questions)

---

## 1. Context & Motivation

The original architecture (see `architecture.md`) prescribes:
- **N runners** that experiment on GPUs
- **1 reviewer** that periodically synthesizes findings on CPU
- A **shared knowledge store** (JSONL blackboard) with curated artifacts: leaderboard, dead_ends, insights, claims

This works, but it has properties we may not want:

| Property | Consequence |
|----------|-------------|
| Reviewer is a **hub** | All synthesis flows through one agent. It's a bottleneck and a single point of interpretive failure. |
| Runners are **leaf nodes** | They consume curated summaries but don't interact with each other. No peer-to-peer learning. |
| Roles are **static** | A runner can never synthesize. A reviewer can never experiment. Specialization is imposed, not emergent. |
| Knowledge is **top-down** | Insights flow reviewer → runners. Runners never challenge or extend each other's observations directly. |
| The leaderboard is **self-reported** | Agents report their own val_bpb. There's no validation that a result is reproducible. |

Karpathy's vision in `next_step_discussion.md`:

> "The goal is not to emulate a single PhD student, it's to emulate a research community of them."

A research community has no designated reviewer. Ideas spread through **publication, replication, citation, and gossip**. What follows are protocols modeled on those dynamics.

---

## 2. Protocol 1: Replication

### The idea

When an agent reports an improvement, other agents can **replicate** it — check out the exact commit, run the same 5-minute training, and confirm or refute the result.

### Why it matters

- Results become **socially validated**, not self-reported
- Prevents lucky variance from polluting the collective's knowledge
- Creates a natural "trust score" for findings: replicated 3 times > replicated 0 times
- It's literally how science works

### Schema

```jsonl
// replications.jsonl (append-only)
{
  "id": "repl-a1b2",
  "original_result_id": "res-x7y8",
  "original_agent": "agent-0",
  "original_commit": "abc123",
  "original_bpb": 1.423,
  "replicator": "agent-2",
  "replicated_bpb": 1.428,
  "delta": 0.005,
  "confirmed": true,
  "timestamp": "2025-07-15T03:22:00Z",
  "notes": "Within noise threshold. Confirmed."
}
```

### Agent behavior

```
WHEN planning next experiment:
  IF shared store has un-replicated results with bpb improvement > threshold:
    WITH probability P_replicate (e.g., 0.15):
      Pick the highest-impact un-replicated result
      Check out that exact commit
      Run training
      Publish replication entry (confirmed or refuted)
      Return to own work
```

### Tuning knobs

| Knob | Range | Effect |
|------|-------|--------|
| `P_replicate` | 0.0–0.3 | How much time the collective spends validating vs. exploring. Too high = wasted GPU time re-running known-good experiments. Too low = no validation. |
| `confirmation_threshold` | 0.01–0.05 bpb | How close replicated_bpb must be to original to count as confirmed. |
| `min_improvement_to_replicate` | 0.005–0.02 bpb | Don't bother replicating tiny gains. Only replicate results that would change collective strategy. |

### Tradeoffs

| Pro | Con |
|-----|-----|
| Robust validation without a reviewer | Costs GPU time on re-runs instead of new experiments |
| Self-correcting: bad results get refuted | Could slow convergence if P_replicate is too high |
| Trust emerges from data, not authority | Requires deterministic-enough training (val_bpb variance must be understood) |

### Interaction with other protocols

- **Adoption** (§7): Agents may require a result to be replicated before adopting it as their starting point
- **Contradiction** (§6): A failed replication is a natural contradiction event
- **Gossip** (§4): "I replicated X and it held" is a high-value observation

---

## 3. Protocol 2: Lineage Forking

### The idea

Instead of every agent always starting from the single global best, agents can **adopt another agent's entire branch** as a starting point. This creates a phylogenetic tree of research — a lineage graph.

### Why it matters

- Allows the collective to **hill-climb on multiple ridges simultaneously**
- An agent that's been improving along a direction (e.g., deeper models) builds up momentum — multiple incremental commits that work together. Cherry-picking just the best commit loses that context.
- Creates a legible history: "agent-2's line of inquiry descended from agent-0's attention experiments"
- Enables **speciation**: branches that diverge enough become genuinely different approaches

### Schema

```jsonl
// adoptions.jsonl (append-only)
{
  "id": "adopt-c3d4",
  "child_agent": "agent-3",
  "child_branch": "autoresearch/agent-3-batch-5",
  "parent_agent": "agent-1",
  "parent_commit": "def456",
  "parent_branch": "autoresearch/agent-1-batch-3",
  "reason": "agent-1's optimizer modifications show consistent 3-batch improvement trend. Forking to explore complementary architecture changes on top.",
  "timestamp": "2025-07-15T04:10:00Z"
}
```

### Agent behavior

```
WHEN planning next batch:
  Read recent results across all agents
  Compute: for each agent's branch, the TRAJECTORY (trend over last N experiments)

  IF another agent's trajectory is significantly better than mine:
    WITH probability P_fork:
      Adopt their branch as my new starting point
      Publish adoption entry
      Continue experimenting from there
  ELSE:
    Continue on my own branch
```

### What "trajectory" means

A single good result could be noise. A trajectory is a trend:
- 3+ consecutive improvements along a direction
- Monotonically decreasing bpb over the last K commits
- A large jump followed by continued improvement (not a one-off)

Agents should weight trajectories over individual results when deciding whether to fork.

### Lineage graph

Over time, this produces a tree:

```
agent-0 ──────────────────────────────► (optimizer exploration)
  │
  ├── agent-2 (forked at batch 3) ───► (optimizer + architecture)
  │     │
  │     └── agent-3 (forked at batch 5) ► (optimizer + arch + data aug)
  │
  └── agent-1 (forked at batch 7) ───► (optimizer + regularization)
```

This graph is a first-class artifact. It tells you which lines of inquiry were productive enough to spawn descendants.

### Tradeoffs

| Pro | Con |
|-----|-----|
| Collective climbs multiple hills | Herding: if one agent gets lucky, everyone might fork to it, reducing diversity |
| Preserves incremental progress | Forking costs time (understanding new codebase state) |
| Lineage graph is highly interpretable | Lineage explosion if agents fork too eagerly |

### Anti-herding mechanisms

- **Stochastic forking**: P_fork < 1.0 — not everyone forks to the best branch
- **Fork cooldown**: An agent that just forked can't fork again for N batches
- **Diversity bonus**: When deciding whether to fork, discount branches that already have many descendants
- Combine with **niche differentiation** (§5): even after forking, agents differentiate what they explore on the new branch

---

## 4. Protocol 3: Gossip (Observations)

### The idea

Every agent periodically writes brief **observations** to the shared store. Other agents read them during planning. No synthesis step, no reviewer — agents do their own sense-making.

### Why it matters

- Distributes the "reviewer" function across all agents
- Observations are **first-person** — "I tried X and saw Y" — not filtered through a third party
- Enables **meta-observations**: observations about observations ("runner-2 and runner-4 both report X — I'll investigate the interaction")
- Low overhead: writing a one-paragraph observation is cheap

### Schema

```jsonl
// observations.jsonl (append-only)
{
  "id": "obs-17",
  "agent": "agent-2",
  "type": "observation",
  "category": "architecture/depth",
  "content": "Increasing DEPTH beyond 12 consistently hurts at this batch size. Tried 3 variants (depth 14, 16, 20), all regressed by 0.01-0.03 bpb. Suspect parameter count exceeds what 5 min training can fit.",
  "evidence": ["commit-a1b2", "commit-c3d4", "commit-e5f6"],
  "confidence": "high",
  "timestamp": "2025-07-15T02:45:00Z"
}

// Meta-observation (observation about observations)
{
  "id": "obs-23",
  "agent": "agent-0",
  "type": "meta",
  "content": "Both agent-2 (obs-17) and agent-4 (obs-19) report depth scaling issues. But agent-4 was using a larger batch size. Possibly a depth×batch_size interaction. I'm testing depth=14 with doubled batch size.",
  "references": ["obs-17", "obs-19"],
  "timestamp": "2025-07-15T03:15:00Z"
}
```

### Observation types

| Type | Description | Example |
|------|-------------|---------|
| `observation` | First-person empirical finding | "ReLU² outperformed GELU in my last 3 experiments" |
| `dead_end` | A direction proven unproductive | "Value embedding scaling — tried 5 variants, none beat baseline" |
| `hypothesis` | Untested idea suggested by results | "The warmdown ratio and depth might interact — worth testing jointly" |
| `meta` | Pattern noticed across multiple observations | "Three agents independently found that attention heads > 16 hurts" |
| `question` | Something worth investigating | "Has anyone tested sliding window with depth > 10?" |

### Agent behavior

```
AFTER every batch of K experiments:
  Reflect on what was tried and what was learned
  Write 1-2 observations to observations.jsonl

WHEN planning next batch:
  Read recent observations (last N hours or last M entries)
  Incorporate into planning:
    - Avoid directions marked as dead_end by multiple agents
    - Prioritize directions suggested by hypotheses
    - Investigate contradictions between agents
    - Answer open questions if they fall in your exploration area
```

### Context window management

Agents don't read ALL observations — they read recent ones and filter by relevance:
- Recency: observations from the last N hours
- Relevance: observations whose `category` overlaps with the agent's current exploration area
- Signal: observations with high confidence, or meta-observations that cite multiple sources

The agent's "read-and-plan" step can be a sub-agent with a fresh context window, so observation reading doesn't pollute the main experiment loop.

### Tradeoffs

| Pro | Con |
|-----|-----|
| Every agent contributes to collective knowledge | Observation quality varies — some agents may write noisy observations |
| No bottleneck — synthesis is distributed | No guaranteed "big picture" view — each agent has a partial perspective |
| Meta-observations enable emergent synthesis | Shared store grows linearly with agents × time |
| Low implementation cost | Agents must be good at writing concise, useful observations (prompt engineering) |

---

## 5. Protocol 4: Niche Differentiation

### The idea

Agents **self-select** into under-explored niches based on what others are currently doing. No assigned roles, no claims with TTLs — just a simple economic pressure: prefer areas with less recent activity.

### Why it matters

- Creates **diversity without coordination**
- No claims infrastructure to manage (no TTLs, no stale claims, no cleanup)
- Emergent specialization: agents that happen to be good at a direction stay there; agents that struggle naturally drift to less crowded areas
- Tolerates agent crashes gracefully (no orphaned claims)

### Mechanism

```
WHEN planning next batch:
  Read recent results and observations across all agents

  For each exploration category:
    recent_activity[category] = count of experiments by other agents in last T hours

  attractiveness[category] = (
    base_interest[category]           # From observations, hypotheses, potential
    × (1 / (1 + recent_activity[category]))  # Inverse crowding penalty
    × novelty_bonus[category]          # Bonus for completely unexplored areas
  )

  WITH probability 0.8:
    Pick category with highest attractiveness  # Explore under-served area
  WITH probability 0.2:
    Pick category of the current global best result  # Exploit known good direction
```

### Category taxonomy

Categories should be coarse enough to be useful but fine enough to differentiate:

```
architecture/
  ├── depth
  ├── width (aspect_ratio)
  ├── attention (heads, head_dim, window_pattern)
  ├── mlp (activation, expansion_ratio)
  ├── normalization
  └── positional_encoding

optimizer/
  ├── learning_rates
  ├── schedule (warmup, warmdown)
  ├── weight_decay
  └── algorithm (muon params, adam params)

regularization/
  ├── dropout
  ├── label_smoothing
  └── gradient_clipping

data/
  ├── batch_size
  ├── sequence_length
  └── curriculum
```

Agents can **tag their own experiments** with categories. The taxonomy doesn't need to be exhaustive — agents can create new categories organically.

### Tradeoffs

| Pro | Con |
|-----|-----|
| Zero coordination overhead | Weaker deduplication than explicit claims — two agents might pick the same niche simultaneously |
| Naturally fault-tolerant | Requires reasonable category taxonomy |
| Emergent specialization | Explore/exploit balance needs tuning |
| No state to manage | Less legible than explicit claims ("who's doing what?") |

### Comparison with claims mechanism

| Dimension | Claims (original design) | Niche differentiation |
|-----------|-------------------------|----------------------|
| Coordination | Explicit: "I'm doing X" | Implicit: "X is crowded, I'll do Y" |
| Overhead | Write claim, manage TTL, check for stale claims | Read counts, compute weights, pick |
| Failure mode | Stale claims block directions | Slight duplication (harmless) |
| Legibility | High: you can see exactly who's doing what | Medium: you can infer from recent activity |
| Duplicated work | Rare (if claims work correctly) | Occasional (but duplication can be useful for validation) |

For a small collective (3–5 agents), niche differentiation is likely sufficient. Claims become more valuable at 10+ agents where collision probability increases.

---

## 6. Protocol 5: Contradiction Detection

### The idea

Agents explicitly flag when their results **contradict** another agent's observations. Contradictions are treated as high-signal events that warrant investigation.

### Why it matters

- Contradictions reveal **interaction effects** in the search space
- They prevent premature convergence on wrong conclusions
- A contradiction between two agents is more informative than either agent's result alone
- Creates a natural "attention mechanism" for the collective — contradictions are where the interesting science is

### Schema

```jsonl
// contradictions.jsonl (append-only)
{
  "id": "contra-f7g8",
  "reporter": "agent-1",
  "contradicts": "obs-8",
  "contradicted_agent": "agent-3",
  "description": "agent-3 claims sliding window pattern hurts performance (obs-8), but I got a 0.02 bpb improvement with a modified SSSSSL pattern at depth=10. Possibly a depth-dependent interaction.",
  "my_evidence": ["commit-h9i0"],
  "their_evidence": ["commit-j1k2", "commit-l3m4"],
  "proposed_resolution": "Test sliding window at both depth=8 (agent-3's config) and depth=10 (mine) to isolate the interaction.",
  "timestamp": "2025-07-15T05:00:00Z"
}
```

### Agent behavior

```
WHEN reading observations during planning:
  FOR each recent observation that makes a claim:
    IF my recent results conflict with that claim:
      Publish contradiction entry
      Optionally: prioritize investigating the discrepancy in next batch

WHEN reading contradictions during planning:
  IF a contradiction involves my exploration area:
    Consider designing experiments to resolve it
    (This is high-value work — resolving contradictions produces the most insight)
```

### Contradiction lifecycle

```
1. Agent A publishes observation: "X hurts performance"
2. Agent B finds X helps in a different context → publishes contradiction
3. Either A, B, or a third agent C designs a targeted experiment to resolve it
4. Resolution published as an observation: "X hurts at depth<10, helps at depth≥10"
5. This refined understanding is now available to all agents
```

Contradictions don't need to be "resolved" formally. They're signals. Over time, the observations that follow them naturally refine the collective's understanding.

### Tradeoffs

| Pro | Con |
|-----|-----|
| Surfaces the most informative areas of the search space | Requires agents to be good at recognizing contradictions |
| Prevents groupthink / premature convergence | Could generate noise if agents flag normal variance as contradictions |
| Resolution attempts produce high-quality insights | Agents need enough context to compare their results to others' |

---

## 7. Protocol 6: Adoption Rituals

### The idea

Make the propagation of good results an **active, tracked choice** rather than passive leaderboard reading. Agents explicitly "adopt" results they build on, creating a citation graph.

### Why it matters

- Distinguishes "numerically best" from "actually useful to the collective"
- A result adopted by 4 agents is a genuine breakthrough; a result adopted by 0, even if it has the best bpb, might be an outlier or a dead-end path
- The adoption graph is a **natural measure of impact** — more informative than raw leaderboard rank
- Lets you identify which research directions the collective found worth pursuing

### Schema

```jsonl
// adoptions.jsonl (append-only)
{
  "id": "adopt-p5q6",
  "adopter": "agent-3",
  "adopted_result": "res-r7s8",
  "adopted_agent": "agent-0",
  "adopted_commit": "uvw123",
  "adopted_bpb": 1.398,
  "adoption_type": "fork",
  "reason": "agent-0's attention head reduction consistently improved bpb over 5 commits. Forking to explore whether this combines well with MLP expansion.",
  "timestamp": "2025-07-15T06:30:00Z"
}
```

### Adoption types

| Type | Meaning |
|------|---------|
| `fork` | I'm starting a new branch from this commit (full lineage adoption) |
| `cherry_pick` | I'm taking a specific change and applying it to my branch |
| `config_adopt` | I'm using this result's hyperparameters as my starting point (not the code) |
| `insight_adopt` | I'm not using the code/config, but this result's observation changed my strategy |

### Derived metrics

From adoptions.jsonl, you can compute:

- **Impact score**: How many agents adopted a given result
- **Influence graph**: Which agents' work most influenced the collective
- **Adoption velocity**: How quickly a good result propagates
- **Research lineage**: The full tree of who built on whom

These metrics are purely informational — they're useful for the human observer (and could feed back into agent planning as a signal of which research directions have legs).

### Tradeoffs

| Pro | Con |
|-----|-----|
| Rich provenance and impact tracking | Additional bookkeeping per agent |
| Distinguishes "good number" from "useful to others" | Agents might anchor too heavily on adopted results |
| Citation graph is human-interpretable | |

---

## 8. Comparison Matrix

| Protocol | Solves | Complexity | GPU Cost | Best For |
|----------|--------|-----------|----------|----------|
| **Replication** | Noisy results, false improvements | Low | Medium (re-runs) | Robustness, trust |
| **Lineage Forking** | Isolated hill-climbing, lost context | Medium | None | Preserving momentum, building on others |
| **Gossip** | No peer learning, reviewer bottleneck | Low | None | Knowledge sharing, distributed synthesis |
| **Niche Differentiation** | Redundant exploration, wasted GPU | Low | None | Search space coverage, diversity |
| **Contradiction Detection** | Premature convergence, missed interactions | Medium | None | Deep understanding, finding interaction effects |
| **Adoption Rituals** | No provenance, unclear impact | Low | None | Tracking influence, measuring what matters |

---

## 9. Composition Patterns

These protocols compose naturally. Here are some recommended stacks, ordered from simplest to most complete:

### Minimal viable collective (start here)

```
Gossip + Niche Differentiation
```

Agents share observations and spread out across the search space. This alone gets you 80% of the value of the original runner/reviewer design with zero infrastructure.

- Gossip replaces the reviewer's synthesis role (distributed)
- Niche differentiation replaces the claims mechanism (emergent)
- No new roles, no new infrastructure, no new dependencies

### Robust collective

```
Gossip + Niche Differentiation + Replication
```

Adds validation. Results that matter get independently verified. The leaderboard is no longer self-reported — it's weighted by replication count.

### Full research community

```
Gossip + Niche Differentiation + Replication + Lineage Forking + Contradiction Detection + Adoption Rituals
```

The complete stack. Agents share observations, spread across the search space, validate each other's results, build on each other's branches, flag contradictions, and track provenance. This is the closest analogue to a real research community.

### Incremental adoption path

```
Phase A: Gossip + Niche Differentiation
  → Get basic cross-experiment learning working
  → Validate that agents produce useful observations

Phase B: + Replication
  → Add validation once you have results worth validating
  → Tune P_replicate based on observed variance in val_bpb

Phase C: + Lineage Forking + Adoption
  → Add once you see agents converging on different ridges
  → Lineage graph becomes a key output artifact

Phase D: + Contradiction Detection
  → Add once the collective has enough observations to contradict each other
  → Most valuable at 5+ agents with diverse exploration
```

---

## 10. Role Model: Peers vs. Runner/Reviewer

### Original: hub-and-spoke

```
         ┌──────────┐
         │ Reviewer  │ (single point of synthesis)
         └────┬──────┘
              │ publishes leaderboard + insights
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌────────┐┌────────┐┌────────┐
│Runner 0││Runner 1││Runner 2│  (leaf nodes, consume but don't produce synthesis)
└────────┘└────────┘└────────┘
```

### Proposed: peer-to-peer

```
┌────────┐   reads/writes    ┌────────┐
│ Agent 0 │◄───────────────►│ Agent 1 │
└────┬───┘                   └───┬────┘
     │    ┌──────────────────┐   │
     │    │   Shared Store   │   │
     ├───►│  (observations,  │◄──┤
     │    │   results,       │   │
     │    │   replications,  │   │
     │    │   adoptions)     │   │
     │    └──────────────────┘   │
     │                           │
┌────┴───┐                  ┌───┴────┐
│ Agent 2 │◄──────────────►│ Agent 3 │
└────────┘   reads/writes   └────────┘
```

### Every agent's loop (identical for all agents)

```
┌─────────────────────────────────────────────────┐
│                                                   │
│  1. READ shared store                             │
│     - Recent results from all agents              │
│     - Recent observations                         │
│     - Any contradictions involving my area         │
│     - Recent activity by category (for niche      │
│       differentiation)                            │
│                                                   │
│  2. PLAN next batch                               │
│     - Pick direction (niche differentiation)      │
│     - Pick starting point (own branch, or fork    │
│       another's if trajectory looks better)       │
│     - Decide: should I replicate someone's        │
│       result instead?                             │
│                                                   │
│  3. EXPERIMENT (primary activity, ~80% of time)   │
│     - Modify train.py                             │
│     - Commit, train, evaluate                     │
│     - Keep or discard                             │
│     - Repeat for K experiments                    │
│                                                   │
│  4. PUBLISH                                       │
│     - Write results to results.jsonl              │
│     - Write 1-2 observations to observations.jsonl│
│     - Record any adoptions or contradictions       │
│     - Push git branch                             │
│                                                   │
│  5. GOTO 1                                        │
│                                                   │
└─────────────────────────────────────────────────┘
```

### What about human-readable summaries?

The reviewer's "publish a review to GitHub Discussions" function doesn't require an LLM agent. Options:

1. **Cron script**: A simple Python script (not an LLM agent) that runs periodically, reads the shared store, and renders a markdown summary. 50 lines of code, runs on CPU, no Claude costs.

2. **One peer wears the hat**: Any agent can have an additional periodic task: "every 30 minutes, summarize recent collective progress." This is a skill/loop, not a role.

3. **On-demand**: A human runs `art summary` which reads the shared store and formats it. No automation needed if the human checks in periodically anyway.

The key point: synthesis for machine consumption is distributed (every agent reads and interprets the shared store). Synthesis for human consumption is a formatting task, not an intelligence task.

---

## 11. Shared Store Layout (Revised)

Replacing the original `data/` layout (leaderboard, dead_ends, insights, claims) with one derived from the protocols above:

```
data/
├── results.jsonl              # All experiment results (append-only)
│                              #   {agent, commit, branch, bpb, vram, category, timestamp}
│
├── observations.jsonl         # Agent observations, dead ends, hypotheses (append-only)
│                              #   {agent, type, category, content, evidence[], confidence}
│                              #   types: observation, dead_end, hypothesis, meta, question
│
├── replications.jsonl         # Replication attempts (append-only)
│                              #   {original_result, replicator, replicated_bpb, confirmed}
│
├── adoptions.jsonl            # Branch adoptions and cherry-picks (append-only)
│                              #   {adopter, adopted_result, adopted_commit, type, reason}
│
├── contradictions.jsonl       # Flagged contradictions between observations (append-only)
│                              #   {reporter, contradicts, description, proposed_resolution}
│
└── human_directive.json       # Optional human steering (write-once, read-many)
                               #   {directive, priority, timestamp}
```

### What's gone

| Original artifact | Replaced by |
|-------------------|-------------|
| `leaderboard.jsonl` (curated ranking) | Agents compute rankings on the fly from `results.jsonl` + `replications.jsonl`. No maintained artifact needed. |
| `dead_ends.jsonl` (reviewer-curated) | Observations with `type: "dead_end"` in `observations.jsonl`. Any agent can publish a dead end. |
| `insights.jsonl` (reviewer-curated) | Observations with `type: "observation"` or `type: "meta"`. Synthesis is distributed. |
| `claims/{agent}.json` | Niche differentiation. Agents infer what others are doing from recent activity. No explicit claims. |

### Why append-only JSONL

- **No write conflicts**: Multiple agents appending concurrently is safe (with line-level atomicity, which JSONL provides via `\n`-delimited records)
- **No merge conflicts in git**: Appends don't conflict. Two agents appending to the same file on different branches merge cleanly.
- **Full history**: Nothing is overwritten. You can reconstruct the entire state of knowledge at any point in time.
- **Simple**: `cat`, `grep`, `jq`, `tail` — every agent and every debugging tool can read these files.

### Compaction (if needed)

If files grow too large for agents to read efficiently:
- A periodic compaction job (cron script, not an agent) can produce a `data/snapshots/` directory with recent-window summaries
- Agents read the snapshot + entries since the snapshot timestamp
- The raw JSONL files remain the source of truth

---

## 12. Open Questions

### Protocol design

1. **Observation quality**: How do we ensure agents write useful observations and not noise? Prompt engineering? Structured templates? Post-hoc filtering?

2. **Replication variance**: val_bpb from a 5-minute training run has inherent variance. What's the noise floor? Without knowing this, it's hard to set the confirmation threshold for replications. (Could be empirically measured in Phase A by having one agent run the same config 5 times.)

3. **Category taxonomy**: For niche differentiation, how coarse/fine should categories be? Should agents self-tag, or should categories be inferred from commit diffs?

4. **Observation window**: How far back should agents read? All observations ever? Last N hours? Last N per category? There's a tension between complete knowledge and context window limits.

5. **Cross-agent trust**: Should agents weight observations from agents with better track records more heavily? Or treat all observations equally? Weighting adds complexity but could improve signal-to-noise.

### Implementation

6. **Git concurrency**: Multiple agents appending to the same JSONL file on different branches. Merge strategy? Could use a single shared branch for `data/` while agents use separate branches for `train.py`. Or use a non-git mechanism (shared filesystem direct writes).

7. **Sub-agent for reading**: The "read shared store and plan" step could overflow the main agent's context. A sub-agent with a fresh context window reads the store, synthesizes, and returns a compact planning summary. This is the one place where the sub-agent pattern from the original design still makes sense — not as a role, but as a context management technique.

8. **Observation format**: Free-text observations are flexible but hard to query. Structured observations (JSON with fixed fields) are queryable but constrain expression. Hybrid: structured metadata + free-text content field?

9. **When to publish**: After every experiment? After every batch of K? After a significant result? More frequent publishing = faster propagation but more noise. Less frequent = cleaner signal but slower learning.

### Scaling

10. **Store growth**: With N agents publishing results + observations every batch, the shared store grows at O(N × batches). At 10 agents over 12 hours, how large does this get? Is compaction needed from day one?

11. **Reading cost**: Each agent's planning step reads the shared store. With a large store, this reading step becomes expensive (both in time and in Claude API tokens). How do we keep it efficient?

12. **Agent count sweet spot**: At what N does niche differentiation break down and explicit claims become necessary? Probably somewhere around 8–12, where collision probability in a fixed-size category space exceeds a threshold.
