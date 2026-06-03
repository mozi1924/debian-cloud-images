# SPDX-License-Identifier: GPL-2.0-or-later
"""
Azure Compute Validation - Onboarding Script

One-time setup to prepare an Azure subscription for Compute Validation.
Registers required providers, features, and outputs the RP Service Principal ID.

Usage: python3 onboarding.py --subscription-id <subscription-id>

Reference: https://github.com/Azure/compute-validation-docs
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta

from .utils import log, run_az_command, VALIDATE_RP_APP_ID


# Timeout for waiting for registrations (30 minutes)
REGISTRATION_TIMEOUT_SECONDS = 1800

# Poll interval for checking registration status
REGISTRATION_POLL_INTERVAL = 10


def ensure_az_login() -> None:
    """
    Verify Azure CLI is logged in, prompt for login if not.
    """
    try:
        run_az_command(["account", "show", "-o", "none"])
        log("INFO", "Azure CLI is authenticated")
    except RuntimeError:
        log("INFO", "Not logged in. Please authenticate...")
        run_az_command(["login", "-o", "none"])


def set_subscription(subscription_id: str) -> None:
    """
    Set the active subscription.

    Args:
        subscription_id: Azure subscription ID
    """
    run_az_command(["account", "set", "--subscription", subscription_id])
    sub_name = run_az_command(["account", "show", "--query", "name", "-o", "tsv"])
    log("INFO", f"Using subscription: {sub_name} ({subscription_id})")


def register_feature(namespace: str, name: str) -> None:
    """
    Register a preview feature if not already registered.

    Args:
        namespace: Resource provider namespace
        name: Feature name
    """
    # Check if already registered
    state = run_az_command([
        "feature", "show",
        "--namespace", namespace,
        "--name", name,
        "--query", "properties.state",
        "-o", "tsv"
    ], no_throw=True)

    if state == "Registered":
        log("INFO", f"Feature {namespace}/{name} already registered")
        return

    log("INFO", f"Registering feature: {namespace}/{name}")
    run_az_command([
        "feature", "register",
        "--namespace", namespace,
        "--name", name,
        "--only-show-errors"
    ])


def wait_feature_registered(namespace: str, name: str) -> None:
    """
    Wait for a feature to reach 'Registered' state.

    Args:
        namespace: Resource provider namespace
        name: Feature name

    Raises:
        RuntimeError: If timeout is reached
    """
    deadline = datetime.now() + timedelta(seconds=REGISTRATION_TIMEOUT_SECONDS)

    while datetime.now() < deadline:
        state = run_az_command([
            "feature", "show",
            "--namespace", namespace,
            "--name", name,
            "--query", "properties.state",
            "-o", "tsv"
        ])

        if state == "Registered":
            log("INFO", f"Feature {namespace}/{name} is Registered")
            return

        log("INFO", f"Feature {namespace}/{name} state: {state}, waiting...")
        time.sleep(REGISTRATION_POLL_INTERVAL)

    raise RuntimeError(f"Timeout waiting for feature {namespace}/{name}")


def register_provider(namespace: str) -> None:
    """
    Register a resource provider if not already registered.

    Args:
        namespace: Resource provider namespace
    """
    # Check if already registered
    state = run_az_command([
        "provider", "show",
        "--namespace", namespace,
        "--query", "registrationState",
        "-o", "tsv"
    ], no_throw=True)

    if state == "Registered":
        log("INFO", f"Provider {namespace} already registered")
        return

    log("INFO", f"Registering provider: {namespace}")
    run_az_command([
        "provider", "register",
        "--namespace", namespace,
        "--only-show-errors"
    ])


def wait_provider_registered(namespace: str) -> None:
    """
    Wait for a provider to reach 'Registered' state.

    Args:
        namespace: Resource provider namespace

    Raises:
        RuntimeError: If timeout is reached
    """
    deadline = datetime.now() + timedelta(seconds=REGISTRATION_TIMEOUT_SECONDS)

    while datetime.now() < deadline:
        state = run_az_command([
            "provider", "show",
            "--namespace", namespace,
            "--query", "registrationState",
            "-o", "tsv"
        ])

        if state == "Registered":
            log("INFO", f"Provider {namespace} is Registered")
            return

        log("INFO", f"Provider {namespace} state: {state}, waiting...")
        time.sleep(REGISTRATION_POLL_INTERVAL)

    raise RuntimeError(f"Timeout waiting for provider {namespace}")


def get_sp_object_id(app_id: str) -> str:
    """
    Get the object ID for a service principal by app ID.

    Args:
        app_id: Application (client) ID

    Returns:
        Object ID of the service principal
    """
    log("INFO", f"Looking up Service Principal for app: {app_id}")
    obj_id = run_az_command([
        "ad", "sp", "show",
        "--id", app_id,
        "--query", "id",
        "-o", "tsv"
    ])

    if not obj_id:
        raise RuntimeError(f"Could not find service principal for app ID: {app_id}")

    return obj_id


def main() -> int:
    """
    Main entry point for the onboarding script.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description="One-time setup for Azure Compute Validation"
    )

    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID to onboard"
    )
    parser.add_argument(
        "--skip-linux-prereqs",
        action="store_true",
        help="Skip Linux advanced test prerequisites (LISA)"
    )

    args = parser.parse_args()

    try:
        log("INFO", "Azure Compute Validation - Subscription Onboarding")

        # Step 1: Verify Azure CLI
        log("INFO", "[1/4] Verifying Azure CLI authentication")
        ensure_az_login()
        set_subscription(args.subscription_id)

        # Step 2: Register Microsoft.Validate
        log("INFO", "[2/4] Registering Microsoft.Validate provider")
        register_feature("Microsoft.Validate", "SelfServeVMImageValidation")
        wait_feature_registered("Microsoft.Validate", "SelfServeVMImageValidation")
        register_provider("Microsoft.Validate")
        wait_provider_registered("Microsoft.Validate")
        register_provider("Microsoft.Resources")
        wait_provider_registered("Microsoft.Resources")

        # Step 3: Register LISA prerequisites (optional)
        if not args.skip_linux_prereqs:
            log("INFO", "[3/4] Registering LISA test prerequisites")
            register_feature("Microsoft.AzureImageTestingForLinux", "JobandJobTemplateCrud")
            wait_feature_registered("Microsoft.AzureImageTestingForLinux", "JobandJobTemplateCrud")
            register_provider("Microsoft.AzureImageTestingForLinux")
            wait_provider_registered("Microsoft.AzureImageTestingForLinux")
            for provider in ["Microsoft.Compute", "Microsoft.Network", "Microsoft.Storage"]:
                register_provider(provider)
                wait_provider_registered(provider)
        else:
            log("INFO", "[3/4] Skipping LISA prerequisites (--skip-linux-prereqs)")

        # Step 4: Get Service Principal ID
        log("INFO", "[4/4] Retrieving Azure Validation RP Service Principal ID")
        sp_object_id = get_sp_object_id(VALIDATE_RP_APP_ID)

        log("INFO", "Onboarding complete!")
        log("INFO", f"CV_AZ_VALIDATION_RP_SP_ID: {sp_object_id}")
        log("INFO", "Add this value to GitLab CI variables")

        return 0

    except RuntimeError as e:
        log("ERROR", f"Onboarding failed: {e}")
        log("ERROR", "Check: allowlisting, permissions (Owner/Contributor), Azure CLI auth")
        return 1


if __name__ == "__main__":
    sys.exit(main())
