#!/usr/bin/env python3
"""
Aggregate NIM scan reports from all repositories.

This script:
1. Reads scan reports from all repository directories
2. Aggregates statistics and classifications
3. Generates a summary report in JSON and optionally Markdown format
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Aggregate NIM scan reports from all repositories"
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default="reports",
        help="Directory containing repository scan reports",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="aggregated-report.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--markdown-output",
        type=str,
        default="",
        help="Optional Markdown output file path",
    )
    return parser.parse_args()


def load_repo_reports(reports_dir: Path) -> list[dict[str, Any]]:
    """Load scan reports from all repository directories."""
    reports = []

    if not reports_dir.exists():
        print(f"Reports directory not found: {reports_dir}", file=sys.stderr)
        return reports

    for repo_dir in reports_dir.iterdir():
        if not repo_dir.is_dir():
            continue

        # Skip if it's not a repo directory
        if repo_dir.name.startswith("."):
            continue

        # Look for nim-scan-report.json
        report_file = repo_dir / "nim-scan-report.json"
        if report_file.exists():
            try:
                with open(report_file, "r", encoding="utf-8") as f:
                    report = json.load(f)
                    report["_source_dir"] = str(repo_dir)
                    reports.append(report)
                    print(f"  Loaded: {repo_dir.name}", file=sys.stderr)
            except Exception as e:
                print(f"  Error loading {report_file}: {e}", file=sys.stderr)
        else:
            # Try to find any report file
            for json_file in repo_dir.glob("*.json"):
                if "report" in json_file.name.lower():
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            report = json.load(f)
                            report["_source_dir"] = str(repo_dir)
                            report["_source_file"] = json_file.name
                            reports.append(report)
                            print(f"  Loaded: {repo_dir.name}/{json_file.name}", file=sys.stderr)
                    except Exception as e:
                        print(f"  Error loading {json_file}: {e}", file=sys.stderr)

    return reports


def aggregate_statistics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate statistics from all reports."""
    classifications = Counter()
    support_types = Counter()
    actions_usage = Counter()

    for report in reports:
        # Count classifications
        classification = report.get("classification", "UNKNOWN")
        classifications[classification] += 1

        # Determine support type
        summary = report.get("summary", {})
        supports_local = summary.get("supports_local_nim", False)
        supports_hosted = summary.get("supports_hosted_nim", False)

        if supports_local and supports_hosted:
            support_types["both"] += 1
        elif supports_local:
            support_types["local_only"] += 1
        elif supports_hosted:
            support_types["hosted_only"] += 1
        else:
            support_types["none"] += 1

        # Determine Actions usage
        uses_local = summary.get("uses_local_nim_in_actions", False)
        uses_hosted = summary.get("uses_hosted_nim_in_actions", False)

        if uses_local and uses_hosted:
            actions_usage["both_in_actions"] += 1
        elif uses_local:
            actions_usage["local_in_actions"] += 1
        elif uses_hosted:
            actions_usage["hosted_in_actions"] += 1
        else:
            actions_usage["none_in_actions"] += 1

    return {
        "by_classification": dict(classifications),
        "by_support_type": dict(support_types),
        "by_actions_usage": dict(actions_usage),
    }


def generate_markdown_report(
    reports: list[dict[str, Any]],
    statistics: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate a Markdown summary report."""
    lines = [
        "# NIM Scan Aggregated Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Total Repositories:** {len(reports)}",
        "",
        "## Summary Statistics",
        "",
        "### By Support Type",
        "",
        "| Type | Count |",
        "|------|-------|",
    ]

    for support_type, count in statistics["by_support_type"].items():
        lines.append(f"| {support_type} | {count} |")

    lines.extend([
        "",
        "### By Actions Usage",
        "",
        "| Usage | Count |",
        "|-------|-------|",
    ])

    for usage_type, count in statistics["by_actions_usage"].items():
        lines.append(f"| {usage_type} | {count} |")

    lines.extend([
        "",
        "### By Classification",
        "",
        "| Classification | Count |",
        "|----------------|-------|",
    ])

    for classification, count in sorted(statistics["by_classification"].items()):
        lines.append(f"| {classification} | {count} |")

    lines.extend([
        "",
        "## Repository Details",
        "",
    ])

    for report in reports:
        repo_name = report.get("metadata", {}).get("repo_name", "Unknown")
        classification = report.get("classification", "UNKNOWN")
        description = report.get("classification_description", "")

        lines.extend([
            f"### {repo_name}",
            "",
            f"- **Classification:** {classification}",
            f"- **Description:** {description}",
        ])

        summary = report.get("summary", {})
        lines.extend([
            f"- **Supports Local NIM:** {summary.get('supports_local_nim', False)}",
            f"- **Supports Hosted NIM:** {summary.get('supports_hosted_nim', False)}",
            f"- **Uses Local NIM in Actions:** {summary.get('uses_local_nim_in_actions', False)}",
            f"- **Uses Hosted NIM in Actions:** {summary.get('uses_hosted_nim_in_actions', False)}",
            "",
        ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Markdown report written to: {output_path}", file=sys.stderr)


def main() -> None:
    """Main entry point."""
    args = parse_args()
    reports_dir = Path(args.reports_dir)

    print("Loading repository reports...", file=sys.stderr)
    reports = load_repo_reports(reports_dir)

    if not reports:
        print("No reports found", file=sys.stderr)
        # Create empty report
        empty_report = {
            "metadata": {
                "aggregation_time": datetime.now(timezone.utc).isoformat(),
                "total_repos": 0,
            },
            "summary": {},
            "repositories": [],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(empty_report, f, indent=2)
        return

    print(f"Loaded {len(reports)} reports", file=sys.stderr)

    # Aggregate statistics
    print("Aggregating statistics...", file=sys.stderr)
    statistics = aggregate_statistics(reports)

    # Clean up internal fields from reports
    cleaned_reports = []
    for report in reports:
        cleaned = {k: v for k, v in report.items() if not k.startswith("_")}
        cleaned_reports.append(cleaned)

    # Generate aggregated report
    aggregated = {
        "metadata": {
            "aggregation_time": datetime.now(timezone.utc).isoformat(),
            "total_repos": len(reports),
            "successful_scans": len(reports),
        },
        "summary": statistics,
        "repositories": cleaned_reports,
    }

    # Write JSON report
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2)

    print(f"\nAggregated report written to: {output_path}", file=sys.stderr)

    # Print summary
    print("\n=== Summary ===", file=sys.stderr)
    print(f"Total repositories: {len(reports)}", file=sys.stderr)
    print("\nBy Support Type:", file=sys.stderr)
    for support_type, count in statistics["by_support_type"].items():
        print(f"  {support_type}: {count}", file=sys.stderr)
    print("\nBy Actions Usage:", file=sys.stderr)
    for usage_type, count in statistics["by_actions_usage"].items():
        print(f"  {usage_type}: {count}", file=sys.stderr)

    # Generate Markdown if requested
    if args.markdown_output:
        generate_markdown_report(reports, statistics, Path(args.markdown_output))


if __name__ == "__main__":
    main()
