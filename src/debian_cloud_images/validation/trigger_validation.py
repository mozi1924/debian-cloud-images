# SPDX-License-Identifier: GPL-2.0-or-later
"""Trigger Azure Compute Validation for a Debian cloud image."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from debian_cloud_images.backend.azure.client import AzureClient

from .utils import log


# Test config files in validation/config/ directory
VALIDATION_DIR = Path(__file__).parent
CONFIG_DIR = VALIDATION_DIR / "config"
FAST_VALIDATION_CONFIG = CONFIG_DIR / "computevalidation.testconfig.fast.json"
# TODO: Create computevalidation.testconfig.full.json
# FULL_VALIDATION_CONFIG = CONFIG_DIR / "computevalidation.testconfig.full.json"


def load_testconfig_file(config_file: Path) -> dict[str, Any]:
    """Load and parse a test configuration JSON file."""
    if not config_file.exists():
        raise FileNotFoundError(f"Test config file not found: {config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        params = json.load(f)

    # Extract planConfiguration from the parameters structure
    if "parameters" not in params:
        raise ValueError("Invalid config file: missing 'parameters' key")

    if "planConfiguration" not in params["parameters"]:
        raise ValueError("Invalid config file: missing 'planConfiguration' parameter")

    return params["parameters"]["planConfiguration"]["value"]


def build_plan_configuration(
    vhd_sas_url: str,
    os_type: str,
    architecture_type: str,
    config_file: Path,
    vm_generation: str = "V2"
) -> dict[str, Any]:
    """Build the validation plan configuration from config file and runtime values."""
    config = load_testconfig_file(config_file)

    # Update with runtime values
    config["certificationPackageReference"]["osType"] = os_type
    config["certificationPackageReference"]["architectureType"] = architecture_type
    config["certificationPackageReference"]["vmGenerationType"] = vm_generation
    disk_image = config["certificationPackageReference"]["storageProfile"]["osDiskImage"]
    disk_image["sourceVhdUri"] = vhd_sas_url

    return config


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
def deploy_arm_template(
    subscription_id: str,
    resource_group: str,
    location: str,
    cloud_validation_name: str,
    execution_plan_name: str,
    execution_plan_run_name: str,
    plan_configuration: dict[str, Any],
    az_validation_rp_sp_id: str
) -> dict[str, Any]:
    """Deploy ARM template to create CloudValidation, ExecutionPlan, and Run."""
    template_path = CONFIG_DIR / "computevalidation.template.json"

    if not template_path.exists():
        raise FileNotFoundError(f"ARM template not found: {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    parameters = {
        "location": {"value": location},
        "resourceGroupName": {"value": resource_group},
        "cloudValidationName": {"value": cloud_validation_name},
        "executionPlanName": {"value": execution_plan_name},
        "executionPlanRunName": {"value": execution_plan_run_name},
        "planConfiguration": {"value": plan_configuration},
        "azValidationRpPrincipalId": {"value": az_validation_rp_sp_id}
    }

    deployment_name = f"cv-{cloud_validation_name}-{execution_plan_run_name}"[:64]
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.Resources/deployments/{deployment_name}"
        f"?api-version=2021-04-01"
    )
    payload = {
        "location": location,
        "properties": {
            "mode": "Incremental",
            "template": template,
            "parameters": parameters,
        }
    }

    log("INFO", f"Deploying to subscription {subscription_id} in {location}")

    with AzureClient() as client:
        response = client.put(url, json=payload)
        response.raise_for_status()

        # Poll for async completion
        while response.status_code in (201, 202):
            op_url = (response.headers.get("Azure-AsyncOperation")
                      or response.headers.get("Location"))
            if not op_url:
                break
            time.sleep(10)
            response = client.get(op_url)
            response.raise_for_status()
            data = response.json()
            status = data.get("status", "")
            log("INFO", f"Deployment status: {status}")
            if status in ("Succeeded", "Failed", "Canceled"):
                if status != "Succeeded":
                    raise RuntimeError(f"Deployment failed: {status}")
                return data

    return response.json()


def main() -> int:
    """Main entry point. Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(
        description="Trigger Azure Compute Validation for a Debian cloud image"
    )

    # Required arguments
    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID where validation resources will be created"
    )
    parser.add_argument(
        "--resource-group",
        required=True,
        help="Resource group for validation resources"
    )
    parser.add_argument(
        "--location",
        default="southcentralus",
        help="Azure region (default: southcentralus, currently the only supported region)"
    )
    parser.add_argument(
        "--cloud-validation-name",
        required=True,
        help="Name for the CloudValidation resource (must be unique)"
    )
    parser.add_argument(
        "--execution-plan-name",
        required=True,
        help="Name for the ValidationExecutionPlan resource"
    )
    parser.add_argument(
        "--execution-plan-run-name",
        required=True,
        help="Name for the ExecutionPlanRun resource"
    )
    parser.add_argument(
        "--vhd-sas-url",
        required=True,
        help="SAS URL to the VHD image (must have at least 48 hours expiry)"
    )
    parser.add_argument(
        "--os-type",
        default="Linux",
        choices=["Linux", "Windows"],
        help="Operating system type (default: Linux)"
    )
    parser.add_argument(
        "--architecture-type",
        default="X64",
        choices=["X64", "ARM64"],
        help="CPU architecture type (default: X64)"
    )
    parser.add_argument(
        "--validation-type",
        default="fast",
        choices=["full", "fast"],
        help="Validation type: 'full' (~30 hours) or 'fast' (~30 min). "
             "Determines which config file to use if --config-file is not specified."
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        help="Path to the test configuration JSON file. If not specified, uses "
             "computevalidation.testconfig.fast.json or computevalidation.testconfig.full.json "
             "based on --validation-type"
    )
    parser.add_argument(
        "--vm-generation",
        default="V2",
        choices=["V1", "V2"],
        help="Azure VM generation (default: V2)"
    )
    parser.add_argument(
        "--az-validation-rp-sp-id",
        required=True,
        help="Object ID of Azure Validation RP service principal"
    )

    args = parser.parse_args()

    try:
        log("INFO", "Azure Compute Validation - Trigger")

        # Determine config file
        if args.config_file:
            config_file = args.config_file
        elif args.validation_type.lower() == "full":
            # Full validation config not yet available
            log("WARNING", "Full validation config not available, using fast config")
            config_file = FAST_VALIDATION_CONFIG
        else:
            config_file = FAST_VALIDATION_CONFIG

        log("INFO", f"Using config file: {config_file}")
        log("INFO", "Building validation plan configuration...")
        plan_config = build_plan_configuration(
            vhd_sas_url=args.vhd_sas_url,
            os_type=args.os_type,
            architecture_type=args.architecture_type,
            config_file=config_file,
            vm_generation=args.vm_generation
        )

        log("INFO", f"Validation type: {args.validation_type}")

        deploy_arm_template(
            subscription_id=args.subscription_id,
            resource_group=args.resource_group,
            location=args.location,
            cloud_validation_name=args.cloud_validation_name,
            execution_plan_name=args.execution_plan_name,
            execution_plan_run_name=args.execution_plan_run_name,
            plan_configuration=plan_config,
            az_validation_rp_sp_id=args.az_validation_rp_sp_id
        )

        log("INFO", f"Created: {args.cloud_validation_name}/{args.execution_plan_run_name}")
        log("INFO", "Validation running. Use wait_validation.py to poll.")

        return 0

    except (RuntimeError, FileNotFoundError, ValueError) as e:
        log("ERROR", f"Validation trigger failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
