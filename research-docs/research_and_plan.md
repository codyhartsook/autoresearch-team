# Autoresearch Team — Research & Build Plan

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Understanding the Problem Space](#understanding-the-problem-space)
3. [Question 1: Experiment Tracking](#q1-experiment-tracking)
4. [Question 2: Context Tagging for Agent Updates](#q2-context-tagging)
5. [Question 3: Discussion, Feedback & Ranking](#q3-discussion-feedback--ranking)
6. [Question 4: Compute Infrastructure with Lightning AI](#q4-compute-infra)
7. [Question 5: Modular / Decoupled Architecture](#q5-modularity)
8. [Question 6: Missed Questions](#q6-missed-questions)
9. [Architecture Design](#architecture-design)
10. [Build Plan](#build-plan)

---

## Executive Summary

**The core idea**: Autoresearch (by @karpathy) is a single-agent autonomous ML research loop — one Claude Code agent modifying `train.py`, running 5-minute experiments, keeping improvements, discarding failures, looping indefinitely. Autoresearch Team aims to build a **collective intelligence layer** on top of this: a research committee of N parallel agents that experiment, discuss, rank results, cross-pollinate ideas, and converge faster than any solo agent.

**The inspiration** (from `next_step_discussion.md`): Karpathy envisions "asynchronously massively collaborative" research — a research *community*, not a single PhD student. Git/GitHub is "almost but not really suited." Agents can juggle thousands of commits across arbitrary branch structures. The existing example already shows this pattern: Discussion #43 is a session report, PR #44 is a branch of kept commits, and agents are told to read prior Discussions/PRs for inspiration before starting new sessions.

**Key insight from the real-world data**: Looking at Discussion #43 and PR #44, we can see the actual collaboration pattern emerging:
- Agent runs 126 experiments overnight on `exp/H100/mar8` branch
- Posts a structured session report as a GitHub Discussion
- Opens a (never-merged) PR with exact commit history
- Includes reproducible instructions for other agents to read prior findings
- Each PR/Discussion becomes a "paper" of findings

Our system needs to formalize, automate, and scale this pattern while adding the committee layer.

---

## Understanding the Problem Space

### What autoresearch does today (single agent)

```
LOOP FOREVER:
  1. Modify train.py (one idea)
  2. Git commit with description
  3. Run: uv run train.py > run.log 2>&1 (5 min fixed budget)
  4. Extract metrics: grep val_bpb, peak_vram_mb from run.log
  5. If improved: keep commit, advance branch
  6. If worse: git reset
  7. Log to results.tsv (commit, val_bpb, memory_gb, status, description)
```

**Files**: Only `train.py` gets modified. `prepare.py` is read-only. `program.md` is the agent's instructions. ~630 lines of code total for the model/training loop.

**Output artifacts per experiment**: 
- Git commit (diff of train.py changes)
- Commit message (what was tried)
- `run.log` (full training output)
- Metrics: val_bpb, peak_vram_mb, mfu_percent, total_tokens_M, num_steps
- `results.tsv` row (commit, val_bpb, memory_gb, status, description)

**Output artifacts per session** (multiple experiments):
- A branch of kept commits (e.g., `exp/H100/mar8`)
- `results.tsv` with complete experiment log
- A session report (Discussion or PR body)

### What we want to add

```
N AGENTS → PARALLEL EXPERIMENT SESSIONS
                ↓
     COMMITTEE (discussion, analysis, ranking)
                ↓
     SYNTHESIZED INSIGHTS + NEXT DIRECTIONS
                ↓
     N AGENTS → NEXT ROUND (informed by committee)
```

The committee needs to:
1. See all experiment results with full context
2. Understand *why* each change was tried and what happened
3. Rank/compare parallel experiment branches
4. Generate synthesized insights and propose next directions
5. Distribute these back to experiment runners

---

## Q1: Experiment Tracking

**Core question**: How are experiments tracked? Explore git-based, MLflow, and Lightning AI tracking. Emphasis on group access/review, tracking necessary stats/results/ideas, and facilitating discussions.

### Option A: Git-Native Tracking (Recommended as Primary)

This is what autoresearch already does, and it's the most natural fit.

**How it works today**:
- Each experiment = a git commit on a branch
- Kept experiments advance the branch; discarded experiments get reset
- `results.tsv` captures the full experiment log (including discards)
- Session report posted as Discussion or PR

**Strengths**:
- **Zero new dependencies** — works with existing autoresearch architecture
- **Full reproducibility** — every kept experiment is an exact code snapshot
- **Natural diffing** — `git diff` shows exactly what changed per experiment
- **Branch-as-experiment-lineage** — the commit history IS the experiment history
- **GitHub API access** — agents can read/write Discussions, PRs via `gh` CLI
- **Already proven** — Discussion #43 / PR #44 demonstrate the pattern working

**What to enhance**:
- **Structured commit messages**: Enforce a machine-readable format (JSON front-matter or structured tags) so committee agents can parse experiment context programmatically
- **Branch naming convention**: `exp/{gpu}/{tag}/{agent_id}` (e.g., `exp/H100/mar8/agent-0`)
- **Centralized results aggregation**: A script that collects `results.tsv` across all branches and produces a unified experiment database
- **Rich metadata in results.tsv**: Extend columns to include `hypothesis`, `category` (architecture/hyperparameter/regularization/etc.), `parent_commit`

**Proposed enhanced results.tsv schema**:
```
commit	val_bpb	memory_gb	status	category	hypothesis	description	agent_id	round
a1b2c3d	0.997900	44.0	keep	baseline	-	baseline	agent-0	1
b2c3d4e	0.986041	44.2	keep	batch_size	more steps in fixed budget improves results	halve batch 524K to 262K	agent-0	1
```

**Weaknesses of git-only**:
- No dashboards/visualizations out of the box
- No real-time metric streaming during training
- Aggregating across branches requires custom tooling
- No built-in comparison views (you'd build these)

### Option B: W&B (Weights & Biases) as Secondary Tracking

**Strengths**:
- Best-in-class dashboards for comparing parallel runs
- `wandb.log()` for real-time metric streaming during training
- Group/team workspace with shared projects
- Run comparisons, parameter importance analysis
- Artifact tracking (model weights, configs)
- Python API for programmatic access — agents can query results
- Notes/descriptions per run for semantic context

**Integration approach**: Add minimal W&B instrumentation to `train.py`:
```python
import wandb
run = wandb.init(
    project="autoresearch-team",
    name=f"{agent_id}/{experiment_desc}",
    config={...hyperparameters...},
    tags=[round_id, agent_id, category],
    notes=hypothesis_text,
)
# In training loop:
wandb.log({"train_loss": loss, "lr_multiplier": lrm, "step": step})
# After eval:
wandb.log({"val_bpb": val_bpb, "peak_vram_mb": peak_vram_mb})
```

**Weaknesses**:
- External dependency (SaaS or self-hosted server)
- Adds ~10 lines to train.py per experiment runner
- Free tier has limits; team features require paid plan
- Agents need API keys

### Option C: MLflow

**Strengths**:
- Open source, self-hostable
- Experiment/run/metric tracking with UI
- Model registry
- REST API for programmatic access

**Weaknesses**:
- Requires running an MLflow server (heavier operational burden)
- UI not as polished as W&B for real-time comparison
- Less agent-friendly than W&B (no native AI integrations)
- Overkill for our use case — we don't need model registry, deployment, etc.

### Option D: Lightning AI Experiment Management

**Strengths**:
- Native integration if we're already using Lightning for compute
- Built-in to the platform (no separate service)
- Team collaboration features

**Weaknesses**:
- Tightly coupled to Lightning platform
- Less flexible than W&B for custom metrics
- Less community adoption for this specific pattern

### Recommendation: Git-primary + W&B-secondary

**Git is the source of truth.** Every experiment is a commit, every session is a branch, every session report is a Discussion/PR. This preserves compatibility with upstream autoresearch and adds zero infrastructure.

**W&B is the visualization/analysis layer.** Agents log metrics to W&B during training for real-time dashboards, comparison views, and programmatic querying by committee agents. W&B runs are tagged with git commit hashes so the two systems are linked.

**Why not MLflow**: More ops burden (running a server), less polished UX, and we don't need model registry features. W&B's programmatic API is better suited for agents querying results.

**Why not Lightning Experiment Management as primary**: Too platform-coupled. We want the tracking to work whether we run on Lightning, bare metal, or a different cloud.

---

## Q2: Context Tagging for Agent Updates

**Core question**: How do experiment workers add rich context (reasoning, hypothesis, theory) to updates they make via the autoresearch loop? How can we tag each update so a committee can review the *thinking* behind experiments, not just the results?

### The Context Problem

Today, an autoresearch agent running Claude Code operates in a long loop:
1. Thinks about what to try (internal reasoning)
2. Edits `train.py`
3. Commits with a short message like "halve batch 524K to 262K"
4. Runs training
5. Checks results
6. Keeps or discards

The **reasoning** — *why* the agent tried this, what it expected, what theory it was testing — lives only in the agent's context window. It's not persisted anywhere reviewable. The `results.tsv` description is a single sentence. The commit message is terse.

### Proposed Solution: Structured Experiment Manifests

Each experiment should produce a **machine-readable experiment manifest** alongside the commit. This is a JSON or YAML file that the agent writes before each experiment run.

**`experiment_manifest.json`** (written per-experiment, committed alongside train.py changes):
```json
{
  "experiment_id": "exp-042",
  "agent_id": "agent-0",
  "round": 1,
  "timestamp": "2026-03-11T02:34:00Z",
  "parent_commit": "a1b2c3d",
  "hypothesis": "Halving batch size from 524K to 262K will allow ~2x more optimization steps within the fixed 5-minute budget, which should improve val_bpb because the model is currently undertrained (high number of tokens per step relative to model capacity).",
  "category": "batch_size",
  "tags": ["optimization", "throughput", "step_count"],
  "reasoning": "The fixed time budget means we're trading batch size for step count. At current model size (~50M params), we likely benefit more from additional gradient updates than from the reduced noise of larger batches. Prior work (Discussion #32) suggested this direction.",
  "inspired_by": ["discussion-32", "exp-001-baseline"],
  "expected_outcome": "val_bpb improvement of 0.005-0.015",
  "risk_assessment": "Low risk — easy to revert, no architectural changes",
  "code_changes_summary": "Changed TOTAL_BATCH_SIZE from 2**19 to 2**18",
  "result": {
    "val_bpb": 0.986041,
    "delta": -0.011859,
    "peak_vram_mb": 45200,
    "status": "keep",
    "analysis": "Exceeded expectations — 0.012 improvement is the single largest gain. The step count nearly doubled. This confirms the model was significantly undertrained at 524K batch size."
  }
}
```

### How to Implement Context Capture Without Breaking Autoresearch

**Option A: Modify program.md to instruct agents to write manifests (Recommended)**

Add instructions to `program.md` that tell the agent to write an `experiments/` directory:

```markdown
## Context Tracking

Before each experiment, write `experiments/{experiment_id}.json` with your hypothesis, 
reasoning, and expected outcome. After the experiment runs, update the file with results 
and analysis. Commit the manifest alongside your train.py changes.
```

**Pros**: Zero code changes to train.py. Works with any agent (Claude Code, Codex, etc.). The manifest is just a file the agent creates.

**Cons**: Relies on agent instruction-following. Manifests might be inconsistent.

**Option B: Wrapper script that enforces manifest creation**

Create a `run_experiment.sh` (or Python wrapper) that:
1. Prompts/enforces creation of manifest before running
2. Runs `uv run train.py > run.log 2>&1`
3. Parses results and auto-populates the result section
4. Commits everything together

```python
# experiment_runner.py
def run_experiment(agent_id, manifest_path):
    # Validate manifest exists and has required fields
    manifest = load_manifest(manifest_path)
    assert manifest.get("hypothesis"), "Must provide hypothesis"
    
    # Run training
    subprocess.run(["uv", "run", "train.py"], stdout=log_file, stderr=log_file)
    
    # Parse results
    metrics = parse_run_log("run.log")
    manifest["result"] = metrics
    
    # Log to W&B if configured
    if wandb_enabled:
        wandb.log({**metrics, "hypothesis": manifest["hypothesis"], ...})
    
    # Save updated manifest
    save_manifest(manifest_path, manifest)
    
    # Git commit
    git_commit(f"{manifest['category']}: {manifest['description']}")
```

**Pros**: Enforces structure, auto-populates results, handles W&B logging.

**Cons**: Another file to maintain. Changes the autoresearch loop slightly.

### Feeding Context into Tracking Systems

**To Git**: Manifests are committed as files. Structured commit messages can mirror key manifest fields. Branch README can aggregate session-level insights.

**To W&B**: The experiment runner logs `wandb.config` with all manifest fields (hypothesis, category, tags). `wandb.summary` gets the results. This makes everything queryable:
```python
# Committee agent querying W&B
api = wandb.Api()
runs = api.runs("autoresearch-team", filters={"config.round": 1, "config.category": "batch_size"})
for run in runs:
    print(run.config["hypothesis"], run.summary["val_bpb"])
```

### Recommendation

**Use Option A (program.md instructions) first**, with Option B (wrapper script) as a Phase 2 enhancement. The manifest format should be standardized in a schema so committee agents can reliably parse them. Start simple — even a structured commit message convention gets you 80% of the value:

```
[batch_size] halve batch 524K to 262K

Hypothesis: More steps in fixed budget improves results because model is undertrained
Expected: val_bpb improvement 0.005-0.015
Inspired by: Discussion #32
```

---

## Q3: Discussion, Feedback & Ranking

**Core question**: How do we facilitate discussions/feedback and ranking of parallel experiments? Do we use the same agent for running experiments and for discussion/analysis? Should we use callbacks or skills for incorporating learnings?

### Architecture: Separate Roles, Potentially Same Model

**Recommendation: Distinct agent roles, same underlying model (Claude), different prompts and context.**

| Role | Responsibility | Context |
|------|---------------|---------|
| **Experiment Runner** (N instances) | Execute autoresearch loop, produce manifests/results | `program.md`, `train.py`, prior experiment results |
| **Committee Analyst** (1-3 instances) | Review all results, rank experiments, synthesize insights | All manifests, results.tsv across branches, prior discussions |
| **Trajectory Planner** (1 instance) | Propose next round's experiment directions, distribute assignments | Committee analysis, global experiment history, research frontier |

Using Claude Code for all roles is fine — the differentiation is in the prompt/context, not the model.

### The Discussion/Review Flow

```
ROUND N:
  
  [Phase 1: Execution]  ~60 min (12 experiments per agent)
  ├─ Agent-0: runs experiments on exp/H100/round-N/agent-0
  ├─ Agent-1: runs experiments on exp/H100/round-N/agent-1
  └─ Agent-2: runs experiments on exp/H100/round-N/agent-2
  
  [Phase 2: Reporting]  ~5 min
  ├─ Each agent writes session report (structured manifest + results.tsv)
  ├─ Each agent pushes branch and opens PR / posts Discussion
  └─ Results aggregated into unified experiment database
  
  [Phase 3: Committee Review]  ~15 min
  ├─ Committee reads all session reports + manifests
  ├─ Ranks experiments across agents (global leaderboard)
  ├─ Identifies converging insights (multiple agents found same pattern)
  ├─ Identifies diverging results (agent A found X helps, agent B found X hurts)
  ├─ Synthesizes "committee report" with key findings
  └─ Posts committee report as Discussion
  
  [Phase 4: Trajectory Planning]  ~10 min
  ├─ Planner reads committee report
  ├─ Identifies unexplored directions
  ├─ Proposes experiment assignments for next round
  ├─ Creates "directives" for each agent (areas to focus/avoid)
  └─ Updates shared context (merged best config, known dead ends)
  
  [Phase 5: Distribution]  ~2 min
  ├─ Best config from all agents merged into next round's starting train.py
  ├─ Each agent gets: best train.py + directive + known dead ends
  └─ GOTO ROUND N+1
```

### Ranking Mechanism

**Global experiment ranking** across all agents, per round:

```python
# ranking.py — run by committee agent
def rank_experiments(all_results):
    """Rank all experiments across agents by val_bpb improvement."""
    kept = [r for r in all_results if r["status"] == "keep"]
    kept.sort(key=lambda r: r["delta"])  # most negative delta = biggest improvement
    
    # Identify convergent discoveries
    categories = defaultdict(list)
    for r in kept:
        categories[r["category"]].append(r)
    
    convergent = {cat: exps for cat, exps in categories.items() 
                  if len(set(e["agent_id"] for e in exps)) > 1}
    
    return {
        "global_ranking": kept[:20],
        "convergent_discoveries": convergent,
        "dead_ends": [r for r in all_results if r["status"] == "discard"],
        "best_config_agent": min(kept, key=lambda r: r["val_bpb"])["agent_id"],
    }
```

**Committee voting** (optional, for more sophisticated coordination):
Each committee member independently reads the results and writes a ranked list. Then the rankings are aggregated (e.g., Borda count). This helps avoid groupthink but may be overkill initially.

### Should Runners vs. Discussion Agents Be Different?

**Yes, keep them separate.** Reasons:

1. **Context window management**: A runner agent's context is consumed by the train.py code, run logs, and loop state. A committee agent needs to see ALL experiment results across agents — different context needs.
2. **Interruption concerns**: If a runner agent is also responsible for discussion, it needs to pause its experiment loop, which wastes GPU time.
3. **Specialization**: The runner prompt optimizes for "try things fast, keep/discard quickly." The committee prompt optimizes for "synthesize patterns, think deeply about what worked and why."

### Notification / Callback System vs. Skills

**Recommendation: Use a round-based synchronization model, not real-time callbacks.**

**Why not real-time callbacks**: 
- Long-running agent loops (like Claude Code in autoresearch mode) don't have a standard callback/interrupt mechanism
- Injecting feedback mid-run risks disrupting the agent's reasoning chain
- The 5-minute experiment granularity is already fast enough — waiting for a round to complete (60 min) before incorporating feedback is fine

**Why round-based sync works better**:
- Clean boundaries: run → report → review → plan → run
- Each phase has clear inputs and outputs
- No complex async coordination needed
- Agents start fresh each round with updated context
- Failures in one phase don't corrupt another

**Skills / directives approach** (for round-to-round learning):

Before each round, the trajectory planner writes a **directive file** per agent:

```json
// directives/agent-0-round-2.json
{
  "starting_config": "commit abc123 (best from round 1, val_bpb=0.969686)",
  "focus_areas": [
    "Explore attention pattern alternatives — agent-1 found SSSSSSL promising but didn't fully test",
    "Try combining VE WD with higher embedding WD — agents found them helpful independently"
  ],
  "avoid": [
    "Weight tying — confirmed broken by 2 agents in round 1",
    "Parallel attn+MLP — confirmed harmful by 3 agents",
    "Batch sizes below 131K — causes assertion errors"
  ],
  "known_dead_ends": ["list of all discarded experiments with reasons"],
  "open_questions": [
    "Does the init scale 0.68 finding transfer when depth changes?",
    "Is there a sweet spot for VE WD between 0.003 and 0.005?"
  ]
}
```

This is injected into the agent's context at the start of each round, either by appending to `program.md` or as a separate file the agent reads.

---

## Q4: Compute Infrastructure with Lightning AI

**Core question**: Training requires A100/H100. Explore automation with Lightning AI, specifically `lightning_sdk` and Pipelines.

### Lightning AI Architecture for Autoresearch Team

Lightning AI provides several primitives that map well to our needs:

| Lightning Primitive | Autoresearch Mapping |
|---------------------|---------------------|
| **Studio** | Development environment for the autoresearch repo |
| **Batch Job** | A single experiment session (1 agent, N experiments) |
| **Pipelines** | Full round orchestration (parallel jobs → committee → next round) |
| **Teamspace** | Project workspace with shared storage and budget controls |
| **Machine** | GPU selection (H100, A100, L4) |

### Pipeline Design

```python
import lightning_sdk.pipeline as pipes
from lightning_sdk import Studio, Machine

# The full round as a pipeline
pipeline = pipes.Pipeline(name="autoresearch-round-1")

# Phase 1: Parallel experiment runners
runners = []
for i in range(3):  # 3 parallel agents
    runner = pipes.JobStep(
        name=f"runner-agent-{i}",
        studio=Studio("autoresearch-runner"),
        command=f"python orchestrator.py run-experiments --agent-id agent-{i} --round 1",
        machine=Machine.H100,
    )
    runners.append(runner)

# Phase 2: Aggregation (CPU is fine)
aggregator = pipes.JobStep(
    name="aggregate-results",
    studio=Studio("autoresearch-committee"),
    command="python orchestrator.py aggregate --round 1",
    machine=Machine.CPU_4,
)

# Phase 3: Committee review (needs Claude API, not GPU)
committee = pipes.JobStep(
    name="committee-review",
    studio=Studio("autoresearch-committee"),
    command="python orchestrator.py committee-review --round 1",
    machine=Machine.CPU_4,
)

# Phase 4: Trajectory planning
planner = pipes.JobStep(
    name="trajectory-planning",
    studio=Studio("autoresearch-committee"),
    command="python orchestrator.py plan-next-round --round 1",
    machine=Machine.CPU_4,
)

# Execution order: runners in parallel, then sequential phases
pipeline.run(steps=[*runners, aggregator, committee, planner])
```

### Key Considerations for Lightning AI

**Shared filesystem**: Lightning Pipelines share a single filesystem across stages. This is ideal — experiment results, manifests, and directives can all live on shared storage without explicit data transfer.

**GPU cost optimization**: 
- Only experiment runners need H100s (~$3/hr each on Lightning)
- Committee/planning phases run on CPU (~$0.10/hr)
- A round with 3 agents running 1 hour + 30 min committee = ~$9.05/round
- 8 rounds overnight = ~$72

**Studio snapshotting**: Lightning takes environment snapshots for jobs, guaranteeing reproducibility. This is valuable — each round's environment is captured automatically.

**Alternative: Direct lightning_sdk without Pipelines**

For simpler control, you can use the SDK directly:

```python
from lightning_sdk import Studio, Machine

# Create and configure runner studios
for i in range(3):
    studio = Studio(f"autoresearch-agent-{i}", "autoresearch-team", create_ok=True)
    studio.start(Machine.H100)
    studio.install_plugin("jobs")
    
    # Submit experiment job
    studio.installed_plugins["jobs"].run(
        f"python orchestrator.py run-experiments --agent-id agent-{i} --round 1",
        name=f"round-1-agent-{i}",
        machine=Machine.H100,
    )
```

### Metrics and Logging on Lightning

Lightning has built-in experiment management. However, per our Q1 recommendation:

- **Primary tracking**: Git (in the shared filesystem)
- **Secondary tracking**: W&B (agents log to W&B project during training)
- **Lightning's role**: Compute orchestration, job management, cost tracking
- **Don't use Lightning for ML tracking** — keep tracking decoupled from infra

### Operational Considerations

**Data prep**: `uv run prepare.py` downloads ~6500 shards. This should run once in a shared volume, not per-job. Lightning's Cloud Folders or Data Connections can persist the `~/.cache/autoresearch/` directory.

**Environment setup**: The Studio should have `uv` installed and `uv sync` run. Snapshot this as a template for all runners.

**GPU availability**: Lightning's GPU marketplace supports H100 and A100. Jobs queue if machines are unavailable. For reliability, support both GPU types — autoresearch is designed to find optimal configs per-platform anyway.

---

## Q5: Modular / Decoupled Architecture

**Core question**: The collective intelligence mechanisms should be decoupled from infra and tracking, or at least modular.

### Architectural Layers

```
┌───────────────────────────────────────────────-──┐
│              Orchestration Layer                 │
│  (round management, scheduling, multi-round loop)│
├───────────────────────────────────────────-──────┤
│             Collective Intelligence              │
│  (committee, ranking, synthesis, directives)     │
├────────────────────────────────────────────────-─┤
│              Experiment Execution                │
│  (agent loop, manifest creation, result capture) │
├──────────────────────────────────────────────-───┤
│              Tracking / Storage                  │
│  (git, W&B, results aggregation)                 │
├───────────────────────────────────────────────-──┤
│              Compute Infrastructure              │
│  (Lightning AI, bare metal, cloud VMs)           │
└───────────────────────────────────────────────-──┘
```

### Module Design

Each layer exposes a clean interface. Swapping implementations should be possible.

**`infra/` — Compute Infrastructure (pluggable)**
```python
# Abstract interface
class ComputeBackend(ABC):
    def launch_job(self, command: str, gpu_type: str, agent_id: str) -> JobHandle: ...
    def check_job_status(self, handle: JobHandle) -> JobStatus: ...
    def get_shared_storage_path(self) -> str: ...

# Implementations
class LightningBackend(ComputeBackend): ...
class LocalBackend(ComputeBackend): ...      # For development / single GPU
class SlurmBackend(ComputeBackend): ...      # For HPC clusters
```

**`tracking/` — Experiment Tracking (pluggable)**
```python
class TrackingBackend(ABC):
    def log_experiment_start(self, manifest: ExperimentManifest) -> None: ...
    def log_metrics(self, step: int, metrics: dict) -> None: ...
    def log_experiment_end(self, result: ExperimentResult) -> None: ...
    def query_experiments(self, filters: dict) -> List[ExperimentResult]: ...

class GitTracker(TrackingBackend): ...       # Primary
class WandbTracker(TrackingBackend): ...     # Secondary
class CompositeTracker(TrackingBackend): ... # Wraps multiple trackers
```

**`collective/` — Collective Intelligence (the core innovation)**
```python
class CommitteeReviewer(ABC):
    def review_round(self, all_results: List[ExperimentResult]) -> CommitteeReport: ...
    def rank_experiments(self, results: List[ExperimentResult]) -> RankedResults: ...

class TrajectoryPlanner(ABC):
    def plan_next_round(self, committee_report: CommitteeReport, 
                        history: ExperimentHistory) -> List[AgentDirective]: ...

class ClaudeCommittee(CommitteeReviewer): ...
class ClaudePlanner(TrajectoryPlanner): ...
```

**`execution/` — Experiment Execution**
```python
class ExperimentRunner:
    """Wraps the autoresearch loop with manifest generation and tracking."""
    def __init__(self, agent_id, tracking: TrackingBackend, directive: AgentDirective): ...
    def run_session(self, num_experiments: int = 12) -> SessionReport: ...
```

**`orchestrator.py` — Top-level Orchestration**
```python
class RoundOrchestrator:
    """Manages a full round: parallel execution → committee → planning."""
    def __init__(self, compute: ComputeBackend, tracking: TrackingBackend,
                 committee: CommitteeReviewer, planner: TrajectoryPlanner): ...
    
    def run_round(self, round_id: int, n_agents: int) -> RoundReport: ...
    def run_multi_round(self, n_rounds: int, n_agents: int) -> List[RoundReport]: ...
```

### Key Design Principle: The Collective Intelligence is Just Data + Prompts

The committee doesn't need GPUs. It doesn't need special frameworks. It's:
1. **Read** all experiment manifests and results
2. **Analyze** via LLM (Claude API call with structured prompt)
3. **Write** committee report and agent directives

This means the collective intelligence layer is fundamentally just:
- A data schema (manifests, results, reports, directives)
- A set of prompt templates
- A thin Python shell that reads data, calls Claude API, writes output

This is maximally portable and decoupled.

---

## Q6: Missed Questions

### Q6.1: Validation Set Contamination / Overfitting to Eval

**The problem**: As one commenter on Discussion #43 noted — running hundreds of experiments all evaluated against the same validation set risks overfitting to it. With a team of agents running even more experiments, this risk increases.

**Mitigations**:
- Hold out a true test set that's never used during the agent loop
- Periodically evaluate the best config on the test set to check generalization
- Track the gap between val_bpb and test_bpb over rounds
- Consider using multiple validation shards and rotating which one is used

### Q6.2: Exploration vs. Exploitation Balance

**The problem**: Agents may converge too quickly to local optima, especially if all agents start from the same best config each round.

**Mitigations**:
- **Diversity directives**: Assign different exploration themes per agent (one does architecture changes, one does optimizer changes, one does regularization)
- **Population diversity**: Not all agents should start from the best config. Some could start from promising-but-not-best branches (e.g., a config that's 0.001 worse but architecturally different)
- **Exploration budget**: First K experiments per agent must be "exploratory" (new categories, not refinements)
- **Dead-end cooling**: Once a direction is marked dead by N agents, it's removed from the exploration space for M rounds before being retried

### Q6.3: Convergence Detection / Diminishing Returns

**The problem**: When should the system stop? How do we detect that we've plateaued?

**Approach**:
- Track improvement rate per round (total delta / experiments)
- If the best improvement in a round is below threshold (e.g., < 0.0001 val_bpb) across all agents, consider:
  - Increasing time budget (5 min → 15 min → 30 min) to test if improvements transfer to longer training
  - Switching to a different phase (e.g., scale up the best config to a bigger model)
  - Restarting from a different base architecture

### Q6.4: Agent Cost and Efficiency

**The problem**: Running N Claude Code instances + GPU compute isn't free. What's the ROI?

**Estimates** (per round, 3 agents):
- 3 × H100 for 1 hour = ~$9 (Lightning AI pricing)
- 3 × Claude Code sessions = ~$3-9 (depending on context size and API calls)
- Committee/planning = ~$1-3 (fewer API calls, CPU compute)
- **Total per round: ~$13-21**
- **Per night (8 rounds): ~$100-170**

**Optimization strategies**:
- Use cheaper models (Haiku/Sonnet) for routine experiment execution, Opus for committee
- Cache dead ends across rounds to avoid retrying
- Reduce agents as improvements plateau

### Q6.5: Reproducibility Across GPU Platforms

**The problem**: Autoresearch results are platform-specific (5-min budget means different GPUs produce different optimal configs). How does the team handle heterogeneous hardware?

**Approach**:
- Treat each GPU type as a separate "research track"
- Committee reviews can span tracks but acknowledges platform differences
- Insights about *directions* (e.g., "weight decay on embeddings helps") transfer across platforms even if exact values don't

### Q6.6: Safety / Guardrails

**The problem**: Agents running autonomously with compute access. What prevents runaway costs or destructive actions?

**Guardrails**:
- Lightning AI budget caps per teamspace
- Maximum experiment count per round
- Maximum rounds before human review checkpoint
- All agents run in read-only environments (can only modify train.py in their branch)
- Orchestrator enforces timeouts per phase

### Q6.7: Human-in-the-Loop Touchpoints

**The problem**: When should a human review the system's progress?

**Recommendation**: 
- Committee reports are always posted as GitHub Discussions — human reads them async
- After every N rounds (e.g., 4), a "human checkpoint" flag pauses the loop pending human approval
- Humans can inject directives at any time (edit a `human_directive.json` file)
- The trajectory planner always reads human directives first

---

## Architecture Design

### System Overview

```
                                ┌──────────────────┐
                                │  Human Oversight │
                                │  (async review,  │
                                │   directives)    │
                                └────────┬─────────┘
                                         │
                            ┌────────────▼─────────────┐
                            │     Orchestrator         │
                            │  (multi-round loop)      │
                            │  orchestrator.py         │
                            └─┬──────────┬───────────┬─┘
                              │          │           │
                    ┌─────────▼──┐ ┌─────▼──────┐ ┌─▼──────────┐
                    │  Runner 0  │ │  Runner 1  │ │  Runner 2  │
                    │  (H100)    │ │  (H100)    │ │  (H100)    │
                    │  Claude    │ │  Claude    │ │  Claude    │
                    │  Code      │ │  Code      │ │  Code      │
                    └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
                          │              │              │
                          ▼              ▼              ▼
                    ┌─────────────────────────────────────────┐
                    │         Shared Storage / Git            │
                    │  - branches per agent per round         │
                    │  - experiment manifests (JSON)          │
                    │  - results.tsv per session              │
                    │  - committee reports                    │
                    │  - directives for next round            │
                    └────────────────┬────────────────────────┘
                                     │
                            ┌────────▼────────────-─┐
                            │     Committee         │
                            │  (Claude API, CPU)    │
                            │  - reads all results  │
                            │  - ranks experiments  │
                            │  - synthesizes report │
                            └────────┬────────-─────┘
                                     │
                            ┌────────▼─────────-────┐
                            │   Trajectory Planner  │
                            │  (Claude API, CPU)    │
                            │  - plans next round   │
                            │  - writes directives  │
                            │  - merges best config │
                            └───────────────────-───┘
```

### Data Flow

```
Round N Start:
  Input: best_config.py + directive_agent_i.json + dead_ends.json

  Runner Agent i:
    for each experiment:
      1. Write experiment_manifest.json (hypothesis, category, reasoning)
      2. Modify train.py
      3. Git commit (train.py + manifest)
      4. Run: uv run train.py > run.log 2>&1
      5. Parse metrics from run.log
      6. Update manifest with results
      7. Log to W&B (if enabled)
      8. Update results.tsv
      9. Keep/discard based on val_bpb
    End: Push branch, write session_report.json

  Aggregator:
    1. Collect all results.tsv + session_reports from all agents
    2. Build unified experiment database (all_results_round_N.json)
    3. Compute global rankings

  Committee:
    1. Read all_results_round_N.json + all manifests
    2. Produce committee_report_round_N.md (posted as GitHub Discussion)
    3. Identify key insights, convergent findings, dead ends

  Planner:
    1. Read committee report + experiment history
    2. Select best config (starting point for round N+1)
    3. Write directives for each agent
    4. Update dead_ends.json
    5. If human checkpoint needed, wait for approval

Round N+1 Start:
  Input: updated best_config.py + new directives + updated dead_ends
```

### Directory Structure

```
autoresearch-team/
├── README.md
├── research_and_plan.md         # This document
├── orchestrator.py              # Multi-round orchestration
├── config.yaml                  # Team configuration (n_agents, n_rounds, etc.)
│
├── execution/
│   ├── experiment_runner.py     # Wraps autoresearch loop with manifests
│   ├── manifest_schema.py       # ExperimentManifest dataclass/schema
│   ├── result_parser.py         # Parse run.log → metrics
│   └── session_reporter.py      # Generate session reports
│
├── collective/
│   ├── committee.py             # Committee review + ranking
│   ├── planner.py               # Trajectory planning + directive generation
│   ├── aggregator.py            # Cross-agent result aggregation
│   └── prompts/
│       ├── committee_review.md  # Prompt template for committee
│       ├── trajectory_plan.md   # Prompt template for planner
│       └── session_report.md    # Prompt template for session reports
│
├── tracking/
│   ├── base.py                  # TrackingBackend ABC
│   ├── git_tracker.py           # Git-based tracking
│   ├── wandb_tracker.py         # W&B integration
│   └── composite.py             # Combines multiple trackers
│
├── infra/
│   ├── base.py                  # ComputeBackend ABC
│   ├── lightning_backend.py     # Lightning AI implementation
│   ├── local_backend.py         # Single-machine development
│   └── setup/
│       ├── studio_setup.sh      # Lightning Studio environment setup
│       └── requirements.txt     # Dependencies for orchestrator/committee
│
├── schemas/
│   ├── experiment_manifest.json # JSON schema for manifests
│   ├── session_report.json      # JSON schema for session reports
│   ├── committee_report.json    # JSON schema for committee output
│   └── agent_directive.json     # JSON schema for directives
│
└── data/                        # Runtime data (gitignored)
    ├── rounds/
    │   ├── round-001/
    │   │   ├── agents/
    │   │   │   ├── agent-0/
    │   │   │   │   ├── results.tsv
    │   │   │   │   ├── session_report.json
    │   │   │   │   └── experiments/
    │   │   │   │       ├── exp-001.json
    │   │   │   │       └── exp-002.json
    │   │   │   └── agent-1/...
    │   │   ├── all_results.json
    │   │   ├── committee_report.md
    │   │   └── directives/
    │   │       ├── agent-0.json
    │   │       └── agent-1.json
    │   └── round-002/...
    └── dead_ends.json
```

---

## Build Plan

### Phase 0: Foundation (Week 1)
> Get a single enhanced agent loop working locally before adding multi-agent complexity.

- [ ] **0.1** Define data schemas (manifest, session report, committee report, directive) as JSON schemas + Python dataclasses
- [ ] **0.2** Build `result_parser.py` — parse `run.log` into structured metrics
- [ ] **0.3** Build `experiment_runner.py` — wrapper around autoresearch loop that produces manifests
- [ ] **0.4** Write enhanced `program.md` template that instructs agents to create manifests
- [ ] **0.5** Test: Run a single enhanced agent session locally (or on 1 GPU) and verify manifests + results.tsv are produced correctly
- [ ] **0.6** Build `session_reporter.py` — generates structured session report from results.tsv + manifests

### Phase 1: Tracking & Aggregation (Week 2)
> Multiple experiment results can be collected and compared.

- [ ] **1.1** Build `git_tracker.py` — structured commits, branch management per agent
- [ ] **1.2** Build `aggregator.py` — collect results across branches, produce unified experiment DB
- [ ] **1.3** (Optional) Build `wandb_tracker.py` — W&B integration for real-time dashboards
- [ ] **1.4** Build `composite.py` — composite tracker that wraps git + W&B
- [ ] **1.5** Test: Simulate 3 agents' results (can be mock data), verify aggregation produces correct global rankings

### Phase 2: Collective Intelligence (Week 3)
> Committee agents can review results and produce actionable outputs.

- [ ] **2.1** Write committee review prompt template
- [ ] **2.2** Build `committee.py` — reads aggregated results, calls Claude API, produces committee report
- [ ] **2.3** Write trajectory planning prompt template
- [ ] **2.4** Build `planner.py` — reads committee report, produces directives + merged best config
- [ ] **2.5** Test: Feed real (Phase 0) or synthetic experiment data through committee → planner pipeline, verify output quality

### Phase 3: Orchestration (Week 4)
> A full round runs end-to-end locally.

- [ ] **3.1** Build `local_backend.py` — runs agents sequentially on a single GPU
- [ ] **3.2** Build `orchestrator.py` — ties all phases together (execute → aggregate → committee → plan)
- [ ] **3.3** Build `config.yaml` schema (n_agents, n_rounds, gpu_type, checkpoint_interval, etc.)
- [ ] **3.4** Test: Run a complete 1-round cycle locally (3 sequential agents × 3 experiments each → committee → plan)
- [ ] **3.5** Build multi-round loop with round-to-round state management

### Phase 4: Lightning AI Infrastructure (Week 5)
> Parallel GPU execution on Lightning AI.

- [ ] **4.1** Set up Lightning Teamspace and Studio template (uv sync, data prep, environment snapshot)
- [ ] **4.2** Build `lightning_backend.py` — launch parallel jobs via lightning_sdk
- [ ] **4.3** Configure shared filesystem for cross-agent data access
- [ ] **4.4** Build Lightning Pipeline definition (parallel runners → aggregator → committee → planner)
- [ ] **4.5** Test: Run a full round on Lightning with 3 parallel H100 agents

### Phase 5: Polish & Scale (Week 6+)
> Production hardening, human oversight, optimization.

- [ ] **5.1** Add human checkpoint mechanism (pause after N rounds, post to GitHub Discussion)
- [ ] **5.2** Add budget/cost tracking and alerts
- [ ] **5.3** Add convergence detection (auto-stop when improvements plateau)
- [ ] **5.4** Add exploration/exploitation balancing (diversity directives)
- [ ] **5.5** Build simple web dashboard (or use W&B) for monitoring multi-round progress
- [ ] **5.6** Add dead-end database with cross-round persistence
- [ ] **5.7** Benchmark: Run overnight (8 rounds × 3 agents) and compare total improvement vs. single-agent baseline

### Key Milestones

| Milestone | When | Success Criteria |
|-----------|------|-----------------|
| Single enhanced agent works | End of Phase 0 | One agent produces structured manifests + session report |
| Multi-agent aggregation works | End of Phase 1 | Can merge and rank results from 3 agents |
| Committee produces useful output | End of Phase 2 | Committee report correctly identifies top wins and dead ends |
| Full round runs locally | End of Phase 3 | Execute → aggregate → committee → plan cycle completes |
| Parallel on Lightning AI | End of Phase 4 | 3 H100 agents run in parallel, results aggregated |
| Overnight run beats single agent | End of Phase 5 | Multi-agent system achieves lower val_bpb than single agent in same wall time |

---

## Open Decisions (For Your Input)

1. **Agent framework**: Use Claude Code directly (via CLI), or wrap with the Anthropic Python API? Claude Code is simpler but harder to programmatically control. The API gives more control but requires reimplementing the code editing/git loop.

2. **Number of agents per round**: Start with 3? The tradeoff is cost vs. exploration breadth.

3. **Round duration**: 1 hour (12 experiments) seems like a good starting point. Should we allow dynamic round lengths?

4. **W&B integration**: Is it worth the complexity for Phase 1, or should we start git-only and add W&B later?

5. **Repository structure**: Should autoresearch-team be a separate repo that *wraps* autoresearch (as a submodule/dependency), or should it be a fork that extends it?
