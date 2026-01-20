#!/usr/bin/env python3
"""
Trigger NIM scan workflows in target repositories.

This script:
1. Reads the repository configuration file
2. Triggers the scan workflow in each enabled repository
3. Records the triggered run IDs for later collection
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from github import Github, GithubException


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Trigger NIM scan workflows in target repositories"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/repos.yaml",
        help="Path to repository configuration file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="triggered-runs.json",
        help="Output file for triggered run information",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without actually triggering",
    )
    parser.add_argument(
        "--specific-repos",
        type=str,
        default="",
        help="Comma-separated list of specific repos to trigger (overrides config)",
    )
    return parser.parse_args()


def get_github_token() -> str:
    """Get GitHub token from environment."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("BP_GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN or BP_GITHUB_TOKEN environment variable required", file=sys.stderr)
        sys.exit(1)
    return token


def load_config(config_path: str) -> dict[str, Any]:
    """Load repository configuration."""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_repos_to_scan(config: dict[str, Any], specific_repos: str) -> list[dict[str, Any]]:
    """Get list of repositories to scan."""
    settings = config.get("settings", {})
    default_branch = settings.get("default_branch", "main")
    default_workflow = settings.get("default_workflow", "ci.yml")

    repos = []

    if specific_repos:
        # Use specific repos from command line
        for repo_name in specific_repos.split(","):
            repo_name = repo_name.strip()
            if repo_name:
                repos.append({
                    "name": repo_name,
                    "workflow_file": default_workflow,
                    "branch": default_branch,
                    "exclude_dirs": "",
                    "enabled": True,
                })
    else:
        # Use repos from config
        for repo in config.get("repos", []):
            if not isinstance(repo, dict):
                continue
            if not repo.get("enabled", True):
                continue
            repos.append({
                "name": repo.get("name"),
                "workflow_file": repo.get("workflow_file", default_workflow),
                "branch": repo.get("branch", default_branch),
                "exclude_dirs": repo.get("exclude_dirs", ""),
                "enabled": True,
            })

    return repos


def trigger_workflow(
    gh: Github,
    repo_name: str,
    workflow_file: str,
    branch: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Trigger a workflow in a repository."""
    result = {
        "repo": repo_name,
        "workflow_file": workflow_file,
        "branch": branch,
        "status": "unknown",
        "run_id": None,
        "error": None,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        print(f"  [DRY RUN] Would trigger {workflow_file} on {repo_name}@{branch}", file=sys.stderr)
        result["status"] = "dry_run"
        return result

    try:
        repo = gh.get_repo(repo_name)
        workflow = repo.get_workflow(workflow_file)

        # Trigger the workflow
        success = workflow.create_dispatch(branch)

        if success:
            result["status"] = "triggered"
            print(f"  Triggered {workflow_file} on {repo_name}@{branch}", file=sys.stderr)
        else:
            result["status"] = "failed"
            result["error"] = "create_dispatch returned False"
            print(f"  Failed to trigger {workflow_file} on {repo_name}", file=sys.stderr)

    except GithubException as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"  Error triggering {repo_name}: {e}", file=sys.stderr)

    return result


def get_latest_run_id(
    gh: Github,
    repo_name: str,
    workflow_file: str,
    triggered_after: datetime,
) -> int | None:
    """Get the run ID of the most recently triggered workflow."""
    try:
        repo = gh.get_repo(repo_name)
        workflow = repo.get_workflow(workflow_file)

        # Get recent runs
        runs = workflow.get_runs()

        for run in runs[:10]:  # Check last 10 runs
            if run.created_at.replace(tzinfo=timezone.utc) >= triggered_after:
                return run.id

    except GithubException as e:
        print(f"  Error getting run ID for {repo_name}: {e}", file=sys.stderr)

    return None


def main() -> None:
    """Main entry point."""
    args = parse_args()
    token = get_github_token()

    print("Loading configuration...", file=sys.stderr)
    config = load_config(args.config)

    repos = get_repos_to_scan(config, args.specific_repos)

    if not repos:
        print("No repositories to scan", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(repos)} repositories to scan", file=sys.stderr)

    if args.dry_run:
        print("\n=== DRY RUN MODE ===\n", file=sys.stderr)

    gh = Github(token)
    trigger_time = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    # Trigger workflows
    print("\nTriggering workflows...", file=sys.stderr)
    for repo_config in repos:
        result = trigger_workflow(
            gh=gh,
            repo_name=repo_config["name"],
            workflow_file=repo_config["workflow_file"],
            branch=repo_config["branch"],
            dry_run=args.dry_run,
        )
        results.append(result)

    # Wait and get run IDs
    if not args.dry_run:
        print("\nWaiting for runs to be created...", file=sys.stderr)
        time.sleep(5)  # Wait for GitHub to register the runs

        print("Fetching run IDs...", file=sys.stderr)
        for result in results:
            if result["status"] == "triggered":
                run_id = get_latest_run_id(
                    gh=gh,
                    repo_name=result["repo"],
                    workflow_file=result["workflow_file"],
                    triggered_after=trigger_time,
                )
                if run_id:
                    result["run_id"] = run_id
                    print(f"  {result['repo']}: run_id={run_id}", file=sys.stderr)
                else:
                    print(f"  {result['repo']}: could not get run_id", file=sys.stderr)

    # Generate output
    output = {
        "trigger_time": trigger_time.isoformat(),
        "total_repos": len(repos),
        "triggered": sum(1 for r in results if r["status"] == "triggered"),
        "failed": sum(1 for r in results if r["status"] in ("failed", "error")),
        "dry_run": args.dry_run,
        "runs": results,
    }

    # Write output
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to: {output_path}", file=sys.stderr)
    print(f"  Total: {output['total_repos']}", file=sys.stderr)
    print(f"  Triggered: {output['triggered']}", file=sys.stderr)
    print(f"  Failed: {output['failed']}", file=sys.stderr)


if __name__ == "__main__":
    main()
