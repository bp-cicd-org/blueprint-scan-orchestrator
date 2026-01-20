# Blueprint Scan Orchestrator

Orchestrates NIM scanning across multiple NVIDIA AI Blueprint repositories, collects results, and generates aggregated reports.

## Overview

This orchestrator:

1. **Triggers** scan workflows in configured target repositories
2. **Waits** for all workflows to complete
3. **Collects** scan report artifacts from each repository
4. **Aggregates** results into a comprehensive summary report

## Quick Start

### 1. Configure Target Repositories

Edit `config/repos.yaml` to add repositories to scan:

```yaml
repos:
  - name: NVIDIA-AI-Blueprints/example-repo
    workflow_file: ci.yml
    branch: main
    exclude_dirs: external,vendor
    enabled: true
```

### 2. Configure Secrets

Add the following secrets to this repository:

| Secret | Description |
|--------|-------------|
| `BP_GITHUB_TOKEN` | GitHub PAT with `repo` and `workflow` permissions |

### 3. Run the Orchestrator

- **Manual trigger**: Go to Actions → "Scan All Repositories" → Run workflow
- **Scheduled**: Uncomment the `schedule` section in `.github/workflows/scan-all-repos.yml`

## Configuration

### repos.yaml

```yaml
settings:
  default_branch: main
  default_workflow: ci.yml
  timeout_minutes: 60
  poll_interval_seconds: 30

repos:
  - name: owner/repo-name
    workflow_file: ci.yml      # Workflow file containing the scan job
    branch: main               # Branch to trigger
    exclude_dirs: external     # Directories to exclude from scanning
    enabled: true              # Enable/disable this repo
```

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `dry_run` | Print what would be done without triggering | `false` |
| `specific_repos` | Comma-separated list of specific repos | `''` (all) |
| `skip_wait` | Skip waiting for workflows to complete | `false` |
| `timeout_minutes` | Timeout for waiting on completion | `60` |

## Scripts

### trigger_scans.py

Triggers scan workflows in target repositories.

```bash
python scripts/trigger_scans.py \
  --config config/repos.yaml \
  --output triggered-runs.json \
  --dry-run
```

### collect_reports.py

Waits for completion and collects artifacts.

```bash
python scripts/collect_reports.py \
  --runs-file triggered-runs.json \
  --output-dir reports \
  --timeout 60
```

### aggregate_reports.py

Aggregates all reports into a summary.

```bash
python scripts/aggregate_reports.py \
  --reports-dir reports \
  --output aggregated-report.json \
  --markdown-output aggregated-report.md
```

## Output

### Aggregated Report (JSON)

```json
{
  "metadata": {
    "aggregation_time": "2025-01-20T10:00:00Z",
    "total_repos": 15
  },
  "summary": {
    "by_support_type": {
      "local_only": 3,
      "hosted_only": 5,
      "both": 6,
      "none": 1
    },
    "by_actions_usage": {
      "local_in_actions": 4,
      "hosted_in_actions": 8,
      "both_in_actions": 2,
      "none_in_actions": 5
    },
    "by_classification": {
      "BOTH_SUPPORT_BOTH_ACTIONS": 2,
      "...": "..."
    }
  },
  "repositories": [...]
}
```

### Aggregated Report (Markdown)

A human-readable summary with tables and per-repository details.

## Requirements

- Python 3.11+
- Dependencies: `pip install -r requirements.txt`

## Target Repository Setup

Each target repository must:

1. Have a workflow that includes the NIM scanner
2. Support `workflow_dispatch` trigger
3. Upload scan reports as artifacts

See [nim-docker-scanner Integration Guide](../nim-docker-scanner/docs/zh/integration-guide.md) for details.

## License

See [LICENSE](LICENSE) for details.
