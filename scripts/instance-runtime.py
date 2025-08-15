#!/usr/bin/env python3
"""
Analyze EC2 instance runtime and job execution time for GitHub Actions runners.

Usage:
    instance-runtime.py INSTANCE_ID [INSTANCE_ID ...]
    instance-runtime.py https://github.com/OWNER/REPO/actions/runs/RUN_ID[/job/JOB_ID]
    instance-runtime.py --help
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from functools import partial
from typing import Dict, List, Optional

from dateutil import parser as date_parser

err = partial(print, file=sys.stderr)

def run_command(cmd: List[str]) -> Optional[str]:
    """Run a command and return output, or None on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        err(f"Error running command: {' '.join(cmd)}")
        err(f"Error: {e.stderr}")
        return None






def get_log_streams(instance_id: str, log_group: str = "/aws/ec2/github-runners") -> List[Dict]:
    """Get CloudWatch log streams for an instance."""
    cmd = [
        "aws", "logs", "describe-log-streams",
        "--log-group-name", log_group,
        "--log-stream-name-prefix", instance_id,
        "--query", "logStreams",
        "--output", "json"
    ]
    output = run_command(cmd)
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []
    return []


def get_log_events(log_group: str, log_stream: str, limit: int = 100, start_from_head: bool = False) -> List[Dict]:
    """Get events from a CloudWatch log stream."""
    cmd = [
        "aws", "logs", "get-log-events",
        "--log-group-name", log_group,
        "--log-stream-name", log_stream,
        "--limit", str(limit),
        "--output", "json"
    ]
    if start_from_head:
        cmd.append("--start-from-head")

    output = run_command(cmd)
    if output:
        try:
            result = json.loads(output)
            return result.get("events", [])
        except json.JSONDecodeError:
            return []
    return []


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse various timestamp formats and ensure timezone is set."""
    try:
        dt = date_parser.parse(ts_str)
        # If no timezone info, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None


def extract_timestamp_from_log(message: str) -> Optional[datetime]:
    """Extract timestamp from log message."""
    # Pattern: [Thu Aug 14 00:29:25 UTC 2025]
    match = re.search(r'\[([^]]+UTC \d{4})\]', message)
    if match:
        return parse_timestamp(match.group(1))

    # Pattern: [2025-08-14 17:37:20]
    match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', message)
    if match:
        return parse_timestamp(match.group(1))

    return None


def analyze_instance(instance_id: str, log_group: str = "/aws/ec2/github-runners") -> Dict:
    """Analyze runtime and job execution for an instance."""
    result = {
        "instance_id": instance_id,
        "launch_time": None,
        "termination_time": None,
        "total_runtime_seconds": 0,
        "job_runtime_seconds": 0,
        "jobs": [],
        "state": "unknown",
        "instance_type": "unknown",
        "tags": {}
    }


    # Get CloudWatch logs
    log_streams = get_log_streams(instance_id, log_group)

    # Check if logs are empty (all streams have no events)
    # Note: storedBytes is often 0 even when there's data, so check for event timestamps instead
    logs_empty = all(
        stream.get("firstEventTimestamp") is None and stream.get("lastEventTimestamp") is None
        for stream in log_streams
    ) if log_streams else True

    # Extract instance info from logs
    if log_streams and not logs_empty:
        # Try to get launch time and instance type from runner-setup log
        for stream in log_streams:
            if "/runner-setup" in stream["logStreamName"]:
                # Get first events for launch time
                events = get_log_events(log_group, stream["logStreamName"], limit=50, start_from_head=True)

                # Get the first timestamp from any log entry as approximate launch time
                if not result["launch_time"] and events:
                    for event in events:
                        ts = extract_timestamp_from_log(event.get("message", ""))
                        if ts:
                            result["launch_time"] = ts
                            break

                # Look for instance type and other metadata
                for event in events:
                    msg = event.get("message", "")

                    # Look for instance type in metadata
                    if result["instance_type"] == "unknown":
                        # Try various patterns for instance types
                        patterns = [
                            r'Instance type:\s+(\S+)',
                            r'instance-type["\s:]+([a-z0-9]+\.[a-z0-9]+)',
                            r'EC2_INSTANCE_TYPE=([a-z0-9]+\.[a-z0-9]+)',
                            r'"instance_type":\s*"([a-z0-9]+\.[a-z0-9]+)"',
                            # Common instance type patterns
                            r'\b(g4dn\.\w+|g5\.\w+|g5g\.\w+|t[234]\.\w+|t[34][ag]\.\w+|p[234]\.\w+|p4d\.\w+|c[456]\.\w+|c[56]a\.\w+|m[456]\.\w+|m[56]a\.\w+|r[456]\.\w+)\b',
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, msg, re.IGNORECASE)
                            if match:
                                result["instance_type"] = match.group(1).lower()
                                break

                    # Look for region in metadata
                    if "Region:" in msg:
                        match = re.search(r'Region:\s+(\S+)', msg)
                        if match:
                            result["tags"]["Region"] = match.group(1)

                    # Look for repository name
                    if "Repository:" in msg or "GITHUB_REPOSITORY" in msg:
                        match = re.search(r'Repository:\s+(\S+)|GITHUB_REPOSITORY=(\S+)', msg)
                        if match:
                            repo = match.group(1) or match.group(2)
                            result["tags"]["Repository"] = repo

                # If still no launch time, use the log stream creation time
                if not result["launch_time"] and stream.get("creationTime"):
                    # CloudWatch timestamps are in milliseconds
                    result["launch_time"] = datetime.fromtimestamp(stream["creationTime"] / 1000, tz=timezone.utc)

    # Find termination time
    for stream in log_streams:
        if "/termination" in stream["logStreamName"]:
            events = get_log_events(log_group, stream["logStreamName"])
            for event in events:
                if "proceeding with termination" in event["message"]:
                    ts = extract_timestamp_from_log(event["message"])
                    if ts:
                        result["termination_time"] = ts
                elif "Runner removed from GitHub successfully" in event["message"]:
                    ts = extract_timestamp_from_log(event["message"])
                    if ts and not result["termination_time"]:
                        result["termination_time"] = ts

    # Determine state based on termination time
    if result["termination_time"]:
        result["state"] = "terminated"
    elif result["launch_time"]:
        # If we have launch time but no termination, assume still running
        result["state"] = "running"
        result["termination_time"] = datetime.now(timezone.utc)
        result["still_running"] = True

    # Calculate total runtime
    if result["launch_time"] and result["termination_time"]:
        delta = result["termination_time"] - result["launch_time"]
        result["total_runtime_seconds"] = int(delta.total_seconds())

    # Analyze job execution times
    job_starts = {}
    job_ends = {}

    for stream in log_streams:
        if "/job-started" in stream["logStreamName"]:
            events = get_log_events(log_group, stream["logStreamName"])
            for event in events:
                msg = event.get("message", "")
                # Parse job start events - look for "Job STARTED" pattern
                if "Job STARTED" in msg:
                    # Extract timestamp
                    ts = extract_timestamp_from_log(msg)
                    if ts:
                        # Extract job name and run info
                        # Pattern: "Job STARTED  : Test pip install - multiple versions/install (Run: 16952719799/11, Attempt: 1)"
                        match = re.search(r'Job STARTED\s*:\s*([^(]+)\s*\(Run:\s*(\d+)/(\d+)', msg)
                        if match:
                            job_name = match.group(1).strip()
                            run_id = match.group(2)
                            job_num = match.group(3)
                            job_key = f"{run_id}/{job_num}"
                            job_starts[job_key] = (ts, job_name)

        elif "/job-completed" in stream["logStreamName"]:
            events = get_log_events(log_group, stream["logStreamName"])
            for event in events:
                msg = event.get("message", "")
                # Parse job completion events - look for "Job COMPLETED" pattern
                if "Job COMPLETED" in msg:
                    # Extract timestamp
                    ts = extract_timestamp_from_log(msg)
                    if ts:
                        # Extract job name and run info
                        # Pattern: "Job COMPLETED: Test pip install - multiple versions/install (Run: 16952719799/11, Attempt: 1)"
                        match = re.search(r'Job COMPLETED\s*:\s*([^(]+)\s*\(Run:\s*(\d+)/(\d+)', msg)
                        if match:
                            job_name = match.group(1).strip()
                            run_id = match.group(2)
                            job_num = match.group(3)
                            job_key = f"{run_id}/{job_num}"
                            job_ends[job_key] = (ts, job_name)

    # Match starts and ends
    total_job_time = 0
    for job_key in job_starts:
        if job_key in job_ends:
            start_ts, start_name = job_starts[job_key]
            end_ts, end_name = job_ends[job_key]
            duration = int((end_ts - start_ts).total_seconds())
            total_job_time += duration
            result["jobs"].append({
                "name": start_name or end_name or job_key,
                "start": start_ts.isoformat(),
                "end": end_ts.isoformat(),
                "duration_seconds": duration
            })

    result["job_runtime_seconds"] = total_job_time

    return result


def get_instances_from_github_url(url: str) -> List[str]:
    """Extract instance IDs from a GitHub Actions URL."""
    # Parse the URL
    match = re.match(r'https://github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)(?:/job/(\d+))?', url)
    if not match:
        err(f"Error: Invalid GitHub Actions URL format: {url}")
        return []

    owner, repo, run_id, job_id = match.groups()

    # Get jobs for this run
    cmd = ["gh", "api", f"repos/{owner}/{repo}/actions/runs/{run_id}/jobs"]
    output = run_command(cmd)
    if not output:
        return []

    try:
        jobs_data = json.loads(output)
    except json.JSONDecodeError:
        err(f"Error: Could not parse GitHub API response")
        return []

    instance_ids = []
    jobs = jobs_data.get("jobs", [])

    for job in jobs:
        # If specific job_id provided, filter to that job
        if job_id and str(job.get("id")) != job_id:
            continue

        # Look for instance ID in runner name (format: i-xxxxx)
        runner_name = job.get("runner_name", "")
        match = re.search(r'(i-[0-9a-f]+)', runner_name)
        if match:
            instance_ids.append(match.group(1))

        # Also check labels
        for label in job.get("labels", []):
            match = re.search(r'(i-[0-9a-f]+)', label)
            if match:
                instance_ids.append(match.group(1))

    return list(set(instance_ids))  # Remove duplicates


def format_duration(seconds: int) -> str:
    """Format duration in human-readable format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


# Cache for instance prices to avoid repeated API calls
_price_cache = {}
_pricing_api_warned = False

def get_instance_price(instance_type: str, region: str = "us-east-1") -> float:
    """Get the current on-demand price for an instance type."""
    global _pricing_api_warned

    # Check cache first
    cache_key = f"{instance_type}:{region}"
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    # Try AWS Pricing API (only works from us-east-1 region)
    # Note: This requires the pricing:GetProducts permission
    try:
        cmd = [
            "aws", "pricing", "get-products",
            "--service-code", "AmazonEC2",
            "--region", "us-east-1",  # Pricing API only works in us-east-1
            "--filters",
            f"Type=TERM_MATCH,Field=instanceType,Value={instance_type}",
            f"Type=TERM_MATCH,Field=location,Value={get_region_name(region)}",
            "Type=TERM_MATCH,Field=operatingSystem,Value=Linux",
            "Type=TERM_MATCH,Field=tenancy,Value=Shared",
            "Type=TERM_MATCH,Field=preInstalledSw,Value=NA",
            "--max-items", "1",
            "--output", "json"
        ]

        output = run_command(cmd)
        if output and "PriceList" in output:
            data = json.loads(output)
            price_list = data.get("PriceList", [])
            if price_list:
                price_data = json.loads(price_list[0])
                on_demand = price_data.get("terms", {}).get("OnDemand", {})
                for term in on_demand.values():
                    for price_dimension in term.get("priceDimensions", {}).values():
                        price_per_unit = price_dimension.get("pricePerUnit", {}).get("USD")
                        if price_per_unit:
                            price = float(price_per_unit)
                            _price_cache[cache_key] = price
                            err(f"Got live price for {instance_type} in {region}: ${price:.4f}/hour")
                            return price
    except Exception as e:
        # Pricing API might not be available or have permissions
        if not _pricing_api_warned:
            err(f"Note: Could not fetch live pricing (AWS Pricing API unavailable or no permissions)")
            _pricing_api_warned = True

    # No pricing available
    _price_cache[cache_key] = 0
    return 0


def get_region_name(region_code: str) -> str:
    """Convert region code to region name for pricing API.

    Uses AWS SSM to get the actual region name, falls back to a formatted guess.
    """
    # Try to get from AWS SSM parameters (these are publicly available)
    try:
        cmd = [
            "aws", "ssm", "get-parameter",
            "--name", f"/aws/service/global-infrastructure/regions/{region_code}/longName",
            "--query", "Parameter.Value",
            "--output", "text",
            "--region", region_code
        ]
        output = run_command(cmd)
        if output:
            return output
    except:
        pass

    # Fallback: format the region code into a readable name
    # us-east-1 -> US East 1, eu-west-2 -> EU West 2, etc.
    parts = region_code.split('-')
    if len(parts) >= 3:
        region_map = {
            "us": "US",
            "eu": "EU",
            "ap": "Asia Pacific",
            "ca": "Canada",
            "sa": "South America",
            "me": "Middle East",
            "af": "Africa"
        }
        area = region_map.get(parts[0], parts[0].upper())
        direction = parts[1].capitalize()
        number = parts[2]
        return f"{area} ({direction} {number})"

    # Last resort: just return the code
    return region_code


def calculate_cost(instance_type: str, runtime_seconds: int, region: str = "us-east-1") -> float:
    """Calculate cost based on instance type and runtime."""
    hourly_cost = get_instance_price(instance_type, region)
    if hourly_cost == 0:
        return 0

    hours = runtime_seconds / 3600
    return hourly_cost * hours


def main():
    parser = argparse.ArgumentParser(
        description="Analyze EC2 instance runtime and job execution time for GitHub Actions runners.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s i-0abc123def456789
  %(prog)s i-0abc123def456789 i-0def456abc789012
  %(prog)s https://github.com/owner/repo/actions/runs/123456789
  %(prog)s https://github.com/owner/repo/actions/runs/123456789/job/987654321
  %(prog)s --log-group /custom/log/group i-0abc123def456789
        """
    )

    parser.add_argument(
        "targets",
        nargs="+",
        help="Instance IDs or GitHub Actions URL"
    )

    parser.add_argument(
        "--log-group",
        default="/aws/ec2/github-runners",
        help="CloudWatch Logs group name (default: /aws/ec2/github-runners)"
    )

    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region for pricing (default: us-east-1)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    parser.add_argument(
        "--parallel",
        type=int,
        default=10,
        help="Maximum number of parallel instance lookups (default: 10, use 1 for sequential)"
    )

    args = parser.parse_args()

    # Collect all instance IDs
    instance_ids = []
    for target in args.targets:
        if target.startswith("https://github.com/"):
            ids = get_instances_from_github_url(target)
            if ids:
                err(f"Found instances from GitHub URL: {', '.join(ids)}")
                instance_ids.extend(ids)
            else:
                err(f"Warning: No instances found for URL: {target}")
        elif target.startswith("i-"):
            instance_ids.append(target)
        else:
            err(f"Warning: Skipping invalid target: {target}")

    if not instance_ids:
        err("Error: No valid instance IDs found")
        sys.exit(1)

    # Analyze instances in parallel
    results = []
    total_runtime = 0
    total_job_runtime = 0
    total_cost = 0

    # Determine parallel execution mode
    max_workers = min(args.parallel, len(instance_ids))
    if max_workers > 1:
        err(f"Analyzing {len(instance_ids)} instance(s) with {max_workers} parallel workers...")
    else:
        err(f"Analyzing {len(instance_ids)} instance(s) sequentially...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_instance = {
            executor.submit(analyze_instance, instance_id, args.log_group): instance_id
            for instance_id in instance_ids
        }

        # Process results as they complete
        for future in as_completed(future_to_instance):
            instance_id = future_to_instance[future]
            try:
                result = future.result(timeout=30)  # 30 second timeout per instance

                # Calculate cost
                cost = calculate_cost(result["instance_type"], result["total_runtime_seconds"], args.region)
                result["estimated_cost"] = cost

                # Add to results
                results.append(result)
                total_runtime += result["total_runtime_seconds"]
                total_job_runtime += result["job_runtime_seconds"]
                total_cost += cost

            except Exception as e:
                err(f"Error analyzing {instance_id}: {e}")
                # Add failed result with all required fields
                results.append({
                    "instance_id": instance_id,
                    "error": str(e),
                    "total_runtime_seconds": 0,
                    "job_runtime_seconds": 0,
                    "estimated_cost": 0,
                    "instance_type": "unknown",
                    "state": "error",
                    "launch_time": None,
                    "termination_time": None,
                    "jobs": [],
                    "tags": {}
                })

    # Sort results by instance ID for consistent output
    results.sort(key=lambda x: x.get("instance_id", ""))

    if args.json:
        # JSON output
        output = {
            "instances": results,
            "summary": {
                "total_instances": len(results),
                "total_runtime_seconds": total_runtime,
                "total_job_runtime_seconds": total_job_runtime,
                "total_idle_seconds": total_runtime - total_job_runtime,
                "estimated_total_cost": round(total_cost, 4)
            }
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        # Human-readable output
        print("\n" + "="*80)
        for result in results:
            print(f"\nInstance: {result['instance_id']}")
            print(f"  Type: {result['instance_type']}")
            print(f"  State: {result['state']}")

            if result.get("tags", {}).get("Name"):
                print(f"  Name: {result['tags']['Name']}")

            if result["launch_time"]:
                print(f"  Launch Time: {result['launch_time']}")

            if result["termination_time"]:
                if result.get("still_running"):
                    print(f"  Current Time: {result['termination_time']} (still running)")
                else:
                    print(f"  Termination Time: {result['termination_time']}")

            print(f"  Total Runtime: {format_duration(result['total_runtime_seconds'])} ({result['total_runtime_seconds']}s)")
            print(f"  Job Runtime: {format_duration(result['job_runtime_seconds'])} ({result['job_runtime_seconds']}s)")

            idle_time = result['total_runtime_seconds'] - result['job_runtime_seconds']
            print(f"  Idle Time: {format_duration(idle_time)} ({idle_time}s)")

            if result['total_runtime_seconds'] > 0:
                utilization = (result['job_runtime_seconds'] / result['total_runtime_seconds']) * 100
                print(f"  Utilization: {utilization:.1f}%")

            if result.get("estimated_cost", 0) > 0:
                print(f"  Estimated Cost: ${result['estimated_cost']:.4f}")

            if result["jobs"]:
                print(f"  Jobs ({len(result['jobs'])}):")
                for job in result["jobs"]:
                    print(f"    - {job['name']}: {format_duration(job['duration_seconds'])}")

        print("\n" + "="*80)
        print("SUMMARY")
        print(f"  Total Instances: {len(results)}")
        print(f"  Total Runtime: {format_duration(total_runtime)} ({total_runtime}s)")
        print(f"  Total Job Runtime: {format_duration(total_job_runtime)} ({total_job_runtime}s)")
        print(f"  Total Idle Time: {format_duration(total_runtime - total_job_runtime)} ({total_runtime - total_job_runtime}s)")

        if total_runtime > 0:
            overall_utilization = (total_job_runtime / total_runtime) * 100
            print(f"  Overall Utilization: {overall_utilization:.1f}%")

        if total_cost > 0:
            print(f"  Estimated Total Cost: ${total_cost:.4f} (from AWS Pricing API)")


if __name__ == "__main__":
    main()
