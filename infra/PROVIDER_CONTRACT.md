# Infrastructure Provider Contract

Any infrastructure provider must satisfy these requirements. The infra layer
is **pure plumbing** — it provisions compute, runs commands, and tears down.
It has no knowledge of the protocol, the experiment loop, or how agents
coordinate.

See [`architecture.md`](../architecture.md) § Infrastructure for context.

---

## What a provider must do

### 1. Provision sessions

Create one or more **session groups**.  Each group has a name, instance count,
machine type, and command.  The provider doesn't assign roles — it just
provisions what the config describes.

| Property        | Description                            |
|-----------------|----------------------------------------|
| Count           | Configurable per group (1–N)           |
| Machine         | Configurable per group (GPU or CPU)    |
| Lifetime        | Long-running (hours–days)              |
| Independence    | No dependencies between sessions       |

Sessions must be **independent** — no barriers, no rounds, no shared
lifecycle. One session crashing must not affect other sessions.

### 2. Execute commands

The provider must be able to run shell commands inside each session:

- **Setup command** — install tools, clone repos, install dependencies.
  Runs once when the session starts.
- **Main command** — the long-running process.
  Runs after setup.

Commands are opaque strings provided by the caller. The provider doesn't
interpret them.

### 3. Provide network access

Each session needs outbound network access for:

- **Git** — clone, fetch, push to remote repos (the coordination mechanism)
- **Package registries** — pip, npm, etc. for dependency installation
- **APIs** — Anthropic API, GitHub API, etc.

### 4. Inject credentials

The provider must deliver environment variables to sessions:

| Variable           | Purpose                              |
|--------------------|--------------------------------------|
| `ANTHROPIC_API_KEY`| Claude API access                    |
| `GH_TOKEN`         | Git push/pull for coordination       |
| Provider-specific  | Auth for the provider itself         |

How credentials are delivered is provider-specific (env vars, secrets
manager, `.env` file, etc.).

### 5. Health checking

The provider should expose session status:

- **Running** — session is alive and executing
- **Stopped** — session has exited (crash or normal exit)
- **Not found** — session was deleted or never created

### 6. Teardown

The provider must support:

- **Stop** — gracefully stop all sessions
- **Delete** — permanently remove sessions and associated resources

Teardown must be idempotent — stopping an already-stopped session is a no-op.

---

## What a provider must NOT do

- **No coordination logic** — the provider doesn't know about the
  leaderboard, claims, experiments, or branches.  That's the protocol's job.
- **No scheduling** — sub-agent timing, review cadence, etc. are handled by
  the implementation layer, not infra.
- **No shared filesystem requirement** — sessions coordinate through git.
  The provider doesn't need to set up shared storage.
- **No inter-session communication** — sessions don't talk to each other
  through the provider. They talk through git.

---

## Provider-specific configuration

Each provider has its own config file under `infra/<provider>/`. The config
contains only provider-specific tunables (machine types, account IDs, etc.)
plus the generic session definitions (count, GPU type, commands).

### Generic fields (all providers)

```yaml
sessions:
  - name: "gpu-worker"
    count: 3                    # How many sessions in this group
    gpu_type: "H100"            # GPU type (provider maps to its own enum)
    command: "..."              # Main command to run

  - name: "cpu-worker"
    count: 1
    gpu_type: "CPU"
    command: "..."
```

### Provider-specific fields (example: Lightning AI)

```yaml
teamspace: "my-teamspace"    # Lightning-specific
org: ""                       # Lightning-specific
launch:
  run_setup: true             # Whether to run studio_setup.sh
  stagger_seconds: 5          # Delay between launches
```

---

## Implementing a new provider

1. Create `infra/<provider-name>/`
2. Implement the operations: provision, execute, health check, teardown
3. Add a CLI entry point or extend `art` with a `--provider` flag
4. Add provider-specific config under `infra/<provider-name>/config.yaml`
5. Add e2e tests under `tests/e2e/` (can reuse the test patterns — just
   swap the Studio fixtures for your provider's session abstraction)

### Existing providers

| Provider | Directory | Status |
|----------|-----------|--------|
| Lightning AI | `infra/lightning/` | Active — Studios on cloud GPUs |
| Local (tmux) | `infra/local/` | Planned |
| Slurm | `infra/slurm/` | Planned |
