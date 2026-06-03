# SPDX-License-Identifier: GPL-2.0-or-later
"""
Setup LISA test permissions for Azure Compute Validation.

Creates resource group and assigns RBAC roles for LinuxQualityValidations.
Run AFTER onboarding.py, BEFORE validation pipelines.
"""

from __future__ import annotations

import argparse
import sys

from .utils import log, run_az_command, get_resource_group_scope


def ensure_resource_group(rg_name: str, location: str) -> None:
    """
    Create resource group if it doesn't exist.

    Args:
        rg_name: Resource group name
        location: Azure region
    """
    # Check if RG exists
    exists = run_az_command([
        "group", "exists",
        "--name", rg_name
    ], no_throw=True)

    if exists == "true":
        log("INFO", f"Resource group {rg_name} already exists")
        return

    # Create RG
    log("INFO", f"Creating resource group {rg_name} in {location}")
    run_az_command([
        "group", "create",
        "--name", rg_name,
        "--location", location,
        "-o", "none"
    ])


def check_role_assignment(scope: str, assignee_object_id: str, role_name: str) -> bool:
    """
    Check if a role assignment already exists.

    Args:
        scope: Resource scope (subscription or resource group)
        assignee_object_id: Service principal object ID
        role_name: Role name (e.g., 'Contributor')

    Returns:
        True if assignment exists, False otherwise
    """
    result = run_az_command([
        "role", "assignment", "list",
        "--assignee-object-id", assignee_object_id,
        "--scope", scope,
        "--role", role_name,
        "--query", "[0].id",
        "-o", "tsv"
    ], no_throw=True)

    return bool(result and result.strip())


def ensure_role_assignment(
    scope: str,
    assignee_object_id: str,
    role_name: str,
    assignee_name: str = "Validation RP"
) -> None:
    """
    Assign a role if not already assigned (idempotent).

    Args:
        scope: Resource scope
        assignee_object_id: Service principal object ID
        role_name: Role to assign
        assignee_name: Name for logging
    """
    if check_role_assignment(scope, assignee_object_id, role_name):
        log("INFO", f"{role_name} already assigned to {assignee_name}")
        return

    log("INFO", f"Assigning {role_name} to {assignee_name}")
    run_az_command([
        "role", "assignment", "create",
        "--assignee-object-id", assignee_object_id,
        "--assignee-principal-type", "ServicePrincipal",
        "--role", role_name,
        "--scope", scope,
        "-o", "none"
    ])


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Setup LISA test permissions for Azure Compute Validation"
    )

    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID"
    )
    parser.add_argument(
        "--resource-group",
        required=True,
        help="Resource group for validation resources"
    )
    parser.add_argument(
        "--location",
        required=True,
        help="Azure region (e.g., southcentralus)"
    )
    parser.add_argument(
        "--validation-rp-sp-id",
        required=True,
        help="Validation RP Service Principal Object ID (from onboarding.py)"
    )
    parser.add_argument(
        "--skip-rg-creation",
        action="store_true",
        help="Skip resource group creation (assume it exists)"
    )

    args = parser.parse_args()

    try:
        log("INFO", "LISA Permissions Setup")

        # Set subscription
        run_az_command(["account", "set", "--subscription", args.subscription_id])
        sub_name = run_az_command(["account", "show", "--query", "name", "-o", "tsv"])
        log("INFO", f"Subscription: {sub_name}")

        # Step 1: Ensure resource group exists
        if not args.skip_rg_creation:
            log("INFO", "[1/3] Creating resource group")
            ensure_resource_group(args.resource_group, args.location)
        else:
            log("INFO", "[1/3] Skipping resource group creation")

        # Step 2: Assign Contributor role
        log("INFO", "[2/3] Assigning Contributor role")
        rg_scope = get_resource_group_scope(args.subscription_id, args.resource_group)
        ensure_role_assignment(
            scope=rg_scope,
            assignee_object_id=args.validation_rp_sp_id,
            role_name="Contributor"
        )

        # Step 3: Assign LISA roles
        log("INFO", "[3/3] Assigning LISA roles")

        lisa_roles = [
            "Virtual Machine Contributor",
            "Storage Blob Data Contributor",
            "Network Contributor"
        ]

        for role in lisa_roles:
            ensure_role_assignment(
                scope=rg_scope,
                assignee_object_id=args.validation_rp_sp_id,
                role_name=role
            )

        log("INFO", "LISA permissions setup complete!")
        return 0

    except RuntimeError as e:
        log("ERROR", f"Setup failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
