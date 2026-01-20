#!/usr/bin/env python3
"""
Collect NIM scan reports from triggered workflow runs.

This script:
1. Reads the triggered runs information
2. Polls for workflow completion
3. Downloads scan report artifacts from each repository
"""

import argparse
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from github import Github, GithubException


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Collect NIM scan reports from triggered workflow runs"
    )
    parser.add_argument(
        "--runs-file",
        type=str,
        default="triggered-runs.json",
        help="Path to triggered runs information file",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports",
        help="Directory to store downloaded reports",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout in minutes for waiting on workflow completion",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Poll interval in seconds",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip waiting for workflows to complete",
    )
    return parser.parse_args()


def get_github_token() -> str:
    """Get GitHub token from environment."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("BP_GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN or BP_GITHUB_TOKEN environment variable required", file=sys.stderr)
        sys.exit(1)
    return token


def load_runs_file(runs_file: str) -> dict[str, Any]:
    """Load triggered runs information."""
    path = Path(runs_file)
    if not path.exists():
        print(f"Error: Runs file not found: {runs_file}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_run_status(gh: Github, repo_name: str, run_id: int) -> dict[str, Any]:
    """Check the status of a workflow run."""
    try:
        repo = gh.get_repo(repo_name)
        run = repo.get_workflow_run(run_id)
        return {
            "status": run.status,
            "conclusion": run.conclusion,
            "completed": run.status == "completed",
        }
    except GithubException as e:
        return {
            "status": "error",
            "conclusion": None,
            "completed": False,
            "error": str(e),
        }


def wait_for_completion(
    gh: Github,
    runs: list[dict[str, Any]],
    timeout_minutes: int,
    poll_interval_seconds: int,
) -> list[dict[str, Any]]:
    """Wait for all workflow runs to complete."""
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60

    # Filter runs that have run_id
    pending_runs = [r for r in runs if r.get("run_id")]

    if not pending_runs:
        print("No runs to wait for", file=sys.stderr)
        return runs

    print(f"Waiting for {len(pending_runs)} runs to complete...", file=sys.stderr)

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout_seconds:
            print(f"\nTimeout reached after {timeout_minutes} minutes", file=sys.stderr)
            break

        all_completed = True
        completed_count = 0

        for run in pending_runs:
            if run.get("completed"):
                completed_count += 1
                continue

            status = check_run_status(gh, run["repo"], run["run_id"])
            run["run_status"] = status["status"]
            run["run_conclusion"] = status["conclusion"]

            if status["completed"]:
                run["completed"] = True
                completed_count += 1
                print(f"  {run['repo']}: completed ({status['conclusion']})", file=sys.stderr)
            else:
                all_completed = False

        if all_completed:
            print(f"\nAll {len(pending_runs)} runs completed", file=sys.stderr)
            break

        remaining = len(pending_runs) - completed_count
        print(f"  [{int(elapsed)}s] {completed_count}/{len(pending_runs)} completed, {remaining} remaining...", file=sys.stderr)
        time.sleep(poll_interval_seconds)

    return runs


def download_artifact(
    token: str,
    repo_name: str,
    artifact_id: int,
    output_dir: Path,
) -> bool:
    """Download and extract an artifact."""
    url = f"https://api.github.com/repos/{repo_name}/actions/artifacts/{artifact_id}/zip"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
        response.raise_for_status()

        # Extract zip
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(output_dir)

        return True

    except Exception as e:
        print(f"    Error downloading artifact: {e}", file=sys.stderr)
        return False


def collect_reports(
    gh: Github,
    token: str,
    runs: list[dict[str, Any]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    """Collect scan reports from completed runs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for run in runs:
        repo_name = run["repo"]
        run_id = run.get("run_id")

        if not run_id:
            print(f"  {repo_name}: no run_id, skipping", file=sys.stderr)
            results.append({
                "repo": repo_name,
                "status": "skipped",
                "reason": "no_run_id",
            })
            continue

        if not run.get("completed"):
            print(f"  {repo_name}: not completed, skipping", file=sys.stderr)
            results.append({
                "repo": repo_name,
                "status": "skipped",
                "reason": "not_completed",
            })
            continue

        print(f"  {repo_name}: collecting artifacts...", file=sys.stderr)

        try:
            repo = gh.get_repo(repo_name)
            workflow_run = repo.get_workflow_run(run_id)
            artifacts = workflow_run.get_artifacts()

            # Create repo-specific output directory
            repo_dir = output_dir / repo_name.replace("/", "-")
            repo_dir.mkdir(parents=True, exist_ok=True)

            found_report = False

            for artifact in artifacts:
                # Look for nim-scan-report artifact
                if "nim-scan-report" in artifact.name:
                    print(f"    Found: {artifact.name}", file=sys.stderr)
                    if download_artifact(token, repo_name, artifact.id, repo_dir):
                        found_report = True

            if found_report:
                results.append({
                    "repo": repo_name,
                    "status": "collected",
                    "output_dir": str(repo_dir),
                })
            else:
                # Try to get other reports
                for artifact in artifacts:
                    if any(name in artifact.name for name in ["docker-image-report", "hosted-nim-report"]):
                        print(f"    Found: {artifact.name}", file=sys.stderr)
                        download_artifact(token, repo_name, artifact.id, repo_dir)
                        found_report = True

                if found_report:
                    results.append({
                        "repo": repo_name,
                        "status": "partial",
                        "output_dir": str(repo_dir),
                    })
                else:
                    results.append({
                        "repo": repo_name,
                        "status": "no_artifacts",
                    })

        except GithubException as e:
            print(f"    Error: {e}", file=sys.stderr)
            results.append({
                "repo": repo_name,
                "status": "error",
                "error": str(e),
            })

    return results


def main() -> None:
    """Main entry point."""
    args = parse_args()
    token = get_github_token()

    print("Loading triggered runs...", file=sys.stderr)
    runs_data = load_runs_file(args.runs_file)

    if runs_data.get("dry_run"):
        print("Runs file is from a dry run, nothing to collect", file=sys.stderr)
        sys.exit(0)

    runs = runs_data.get("runs", [])
    if not runs:
        print("No runs to collect", file=sys.stderr)
        sys.exit(0)

    gh = Github(token)

    # Wait for completion
    if not args.skip_wait:
        runs = wait_for_completion(
            gh=gh,
            runs=runs,
            timeout_minutes=args.timeout,
            poll_interval_seconds=args.poll_interval,
        )

    # Collect reports
    print("\nCollecting reports...", file=sys.stderr)
    output_dir = Path(args.output_dir)
    results = collect_reports(gh, token, runs, output_dir)

    # Summary
    collected = sum(1 for r in results if r["status"] == "collected")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = sum(1 for r in results if r["status"] in ("error", "no_artifacts", "skipped"))

    print(f"\nCollection complete:", file=sys.stderr)
    print(f"  Collected: {collected}", file=sys.stderr)
    print(f"  Partial: {partial}", file=sys.stderr)
    print(f"  Failed/Skipped: {failed}", file=sys.stderr)

    # Write collection results
    collection_results = {
        "collection_time": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "results": results,
        "summary": {
            "collected": collected,
            "partial": partial,
            "failed": failed,
        },
    }

    results_file = output_dir / "collection-results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(collection_results, f, indent=2)

    print(f"\nResults written to: {results_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
