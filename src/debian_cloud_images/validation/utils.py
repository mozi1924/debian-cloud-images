# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared utilities for Azure Compute Validation scripts."""

from __future__ import annotations

import httpx
import subprocess
from datetime import datetime
from typing import Any


# Microsoft.Validate API version
API_VERSION = "2026-02-01-preview"

# Azure Resource Manager endpoint
ARM_HOST = "management.azure.com"


def log(level: str, message: str) -> None:
    """Write a log message with timestamp and level."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] {message}")


def run_az_command(args: list[str], no_throw: bool = False) -> str:
    """
    Execute an Azure CLI command.

    Args:
        args: Arguments to pass to 'az' command
        no_throw: If True, don't raise exception on failure

    Returns:
        Command stdout as trimmed string

    Raises:
        RuntimeError: If command fails and no_throw is False
    """
    log("DEBUG", f"Running: az {' '.join(args)}")

    result = subprocess.run(
        ["az"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False
    )

    out = result.stdout.strip() if result.stdout else ""
    err = result.stderr.strip() if result.stderr else ""

    if result.returncode != 0 and not no_throw:
        raise RuntimeError(f"az command failed: {err or out}")

    return out


def format_duration(seconds: int) -> str:
    """Format seconds to human-readable string like '2h 30m 15s'."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def build_resource_uri(
    subscription_id: str,
    resource_group: str,
    cloud_validation: str,
    execution_plan: str,
    execution_plan_run: str
) -> str:
    """Build the ARM URI for an ExecutionPlanRun resource."""
    return (
        f"https://{ARM_HOST}"
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Validate"
        f"/cloudValidations/{cloud_validation}"
        f"/validationExecutionPlans/{execution_plan}"
        f"/executionPlanRuns/{execution_plan_run}"
        f"?api-version={API_VERSION}"
    )


def get_execution_plan_run(uri: str, client: httpx.Client) -> dict[str, Any]:
    """
    Fetch an ExecutionPlanRun resource from Azure.

    Args:
        uri: Full ARM URI for the ExecutionPlanRun
        client: Authenticated httpx client

    Returns:
        Full API response as dictionary

    Raises:
        httpx.HTTPStatusError: If the API call fails
    """
    response = client.get(uri)
    response.raise_for_status()
    return response.json()


# Well-known application ID for Azure Validation RP (same across all tenants)
VALIDATE_RP_APP_ID = "f877b90d-59ee-40e3-8d2c-215dae4c80d8"


def get_resource_group_scope(subscription_id: str, rg_name: str) -> str:
    """Get the ARM scope for a resource group."""
    return f"/subscriptions/{subscription_id}/resourceGroups/{rg_name}"
