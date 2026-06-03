# SPDX-License-Identifier: GPL-2.0-or-later
"""
Wait for Azure Compute Validation to complete.

Polls ExecutionPlanRun until terminal state (Succeeded/Failed) or timeout.
Terminal states: Succeeded, Failed, Canceled
Running states: Accepted, Running, Updating, Creating
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from debian_cloud_images.backend.azure.client import AzureClient

from .utils import log, format_duration, build_resource_uri, get_execution_plan_run


# Terminal states where we stop polling
TERMINAL_STATES = {"Succeeded", "Failed", "Canceled"}


def get_state_and_response(uri: str, client: AzureClient) -> tuple[str, dict[str, Any]]:
    """Fetch ExecutionPlanRun and extract state. Returns (state, response)."""
    response = get_execution_plan_run(uri, client)
    state = response.get("properties", {}).get("provisioningState", "Unknown")
    return state, response


def wait_for_completion(
    uri: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
    client: AzureClient,
) -> tuple[bool, str, dict[str, Any]]:
    # pylint: disable=too-many-locals
    """
    Poll ExecutionPlanRun until terminal state or timeout.

    Polls at regular intervals, logging progress. Stops when:
    - Terminal state reached (Succeeded/Failed/Canceled)
    - Timeout exceeded

    Returns:
        (success, final_state, response) - success is True only if Succeeded
    """
    start_time = datetime.now()
    deadline = start_time + timedelta(seconds=timeout_seconds)
    poll_count = 0
    timeout_str = format_duration(timeout_seconds)
    interval_str = format_duration(poll_interval_seconds)
    log("INFO", f"Polling: timeout={timeout_str}, interval={interval_str}")

    while datetime.now() < deadline:
        poll_count += 1
        elapsed = (datetime.now() - start_time).total_seconds()

        try:
            state, response = get_state_and_response(uri, client)

            # Log progress
            elapsed_str = format_duration(int(elapsed))
            log("INFO", f"Poll #{poll_count}: State={state}, Elapsed={elapsed_str}")

            # Check if we've reached a terminal state
            if state in TERMINAL_STATES:
                log("INFO", f"Terminal state: {state}")

                # Extract test run summary if available
                properties = response.get("properties", {})
                test_runs = properties.get("testRuns", [])

                if test_runs:
                    status_counts: dict[str, int] = {}
                    for run in test_runs:
                        status = run.get("status", "Unknown")
                        status_counts[status] = status_counts.get(status, 0) + 1
                    summary = ", ".join(f"{s}:{c}" for s, c in sorted(status_counts.items()))
                    log("INFO", f"  Tests: {summary}")

                success = state == "Succeeded"
                return success, state, response

            # Still running, wait before next poll
            time.sleep(poll_interval_seconds)

        except RuntimeError as e:
            log("WARNING", f"Poll #{poll_count} failed: {e}, retrying...")
            time.sleep(poll_interval_seconds)

    # Timeout reached
    log("ERROR", f"Timeout after {format_duration(timeout_seconds)}")
    log("ERROR", "Check Azure portal or increase timeout")

    # Try one last fetch to get current state
    try:
        state, response = get_state_and_response(uri, client)
        return False, state, response
    except RuntimeError:
        return False, "Timeout", {}


def main() -> int:
    """
    Main entry point for the wait validation script.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # ==========================================================================
    # Argument Parsing
    # ==========================================================================
    parser = argparse.ArgumentParser(
        description="Wait for Azure Compute Validation to complete",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Wait with default timeout (6 hours)
  python3 wait_validation.py \\
    --subscription-id 12345678-1234-1234-1234-123456789abc \\
    --resource-group debian-validation-rg \\
    --cloud-validation debian-cv-123 \\
    --validation-execution-plan ep-bookworm-amd64-456 \\
    --execution-plan-run epr-789

  # Wait with custom timeout and poll interval
  python3 wait_validation.py \\
    --subscription-id ... \\
    --resource-group ... \\
    --cloud-validation ... \\
    --validation-execution-plan ... \\
    --execution-plan-run ... \\
    --timeout 7200 \\
    --poll-interval 60
        """
    )

    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID"
    )
    parser.add_argument(
        "--resource-group",
        required=True,
        help="Resource group containing validation resources"
    )
    parser.add_argument(
        "--cloud-validation",
        required=True,
        help="Name of the CloudValidation resource"
    )
    parser.add_argument(
        "--validation-execution-plan",
        required=True,
        help="Name of the ValidationExecutionPlan resource"
    )
    parser.add_argument(
        "--execution-plan-run",
        required=True,
        help="Name of the ExecutionPlanRun resource"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=21600,  # 6 hours
        help="Maximum time to wait in seconds (default: 21600 = 6 hours)"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,  # 5 minutes
        help="Time between status checks in seconds (default: 300 = 5 minutes)"
    )

    args = parser.parse_args()

    # ==========================================================================
    # Execution
    # ==========================================================================
    try:
        log("INFO", "Azure Compute Validation - Wait for Completion")
        log("INFO", f"Resource: {args.cloud_validation}/{args.execution_plan_run}")

        # Build the resource URI
        uri = build_resource_uri(
            subscription_id=args.subscription_id,
            resource_group=args.resource_group,
            cloud_validation=args.cloud_validation,
            execution_plan=args.validation_execution_plan,
            execution_plan_run=args.execution_plan_run
        )

        # Wait for completion
        with AzureClient() as client:
            success, final_state, _ = wait_for_completion(
                uri=uri,
                timeout_seconds=args.timeout,
                poll_interval_seconds=args.poll_interval,
                client=client,
            )

        if success:
            log("INFO", "Validation completed successfully!")
            return 0

        log("ERROR", f"Validation failed: {final_state}")
        if final_state == "Failed":
            log("ERROR", "Infrastructure failure - check Azure portal")

        return 1

    except RuntimeError as e:
        log("ERROR", f"Wait operation failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
