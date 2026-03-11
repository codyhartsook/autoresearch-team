# Autoresearch Team

Autonomous ML research team and review comitee

Core repository: [autoresearch](https://github.com/karpathy/autoresearch)  
Local reference: `~/Github/autoresearch`  
Inspiration discussion: `next_step_discussion.md`

## Exploration

**Design philosophy:** This project aim to build a research team on top of autoresearch. The hypothesis is that collective intelegence (idea exploration, insights sharing, review, experiment distribution) could improve upon a single agent autonomous ml trainer. 

A possible collective intel flow for the team could look like: a training period is run, track metrics and results. The team then discusses the the results to generate n improvements, reasoning behind, hypothesis, etc. N experiment runners then repeat the process, run for a period, track metrics and results. The team then discuses and ranks different experiments, propose new ideas, determine if some approaches should be abandoned. Continue for n rounds. This could be refined, optimized to formulate a full system.

**Open design questions:**
* How are experiments tracked? explore git based tracking, mlflow based tracking, and lightning-ai litlogger based tracking. Emphasize group access/review, what are the strengths of each in terms of tracking necesary stats, results, and core ideas behind the experiment. Also how we could faciliate discussions or at least be a source of info for a discussion.

* How do the experiment workers/runners add context to updates they make via autoresearch loop. Take claude-code for instance, if its running a long experiment loop, update train.py, run training round, analyze results, repeat -- how can we tag each update with the necesary context, reasoning behind the update etc, so that we can review and analyze the experiment in a committee? How can this context get fed into our ml experiment tracking system of choice (previous question).

* If claude-code or openai codex are the workers using autoresearch, how we faciliate discussions / feedback and maybe even ranking of parallel experiments. Do we use the same agent (claude-code) for both running experiments and discussion / analysis and trajectory planning? For experiment runners should we create skills that help incorporate learnings or should use some callback system to long-running agents are notified when feedback/analysis/voting has been completed?

* Compute infra setup: training will require an a100 or h100, explore an automation setup using lightning-ai. How can we launch a team of trainers using lightning_sdk or lightning-cli, pipelines seem promissing. Note that we should consider the tracking here too, how are metrics, logs, results, and semantic context tracked. Could create agent skill for this.

* When building the system, ideally we want the collective intelegence mechanisms decoupled from infra and tracking or at least modular.

* Any important questions I might have missed?


## Architecture
tbd

