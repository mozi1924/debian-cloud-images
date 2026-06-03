# SPDX-License-Identifier: GPL-2.0-or-later
"""
Retrieve and format Azure Compute Validation results.

Outputs: JSON (full results), JUnit XML (CI integration), Console summary.
Critical suites (BasicVMValidation, MalwareValidation) block certification.
Non-critical suites are warnings only.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any
from xml.dom import minidom

from debian_cloud_images.backend.azure.client import AzureClient

from .utils import log, build_resource_uri, get_execution_plan_run


# Test statuses
STATUS_PASSED = "Passed"
STATUS_FAILED = "Failed"
STATUS_SKIPPED = "Skipped"
STATUS_ERROR = "Error"

# Critical test suites - failures in these block marketplace certification
CRITICAL_SUITES = {
    "BasicVMValidation",
    "MalwareValidation",
}

# Non-critical test suites - failures are warnings but don't block
NON_CRITICAL_SUITES = {
    "VulnerabilityValidation",
    "LinuxQualityValidations",
}

# Status to counter key mapping
STATUS_COUNTER_MAP = {
    STATUS_PASSED: "passed",
    STATUS_FAILED: "failed",
    STATUS_SKIPPED: "skipped",
}


def _increment_status_counter(counters: dict[str, int], status: str) -> None:
    """Increment the appropriate counter based on test status."""
    key = STATUS_COUNTER_MAP.get(status, "error")
    counters[key] = counters.get(key, 0) + 1


def parse_test_results(response: dict[str, Any]) -> dict[str, Any]:
    """
    Parse validation results into a structured format.

    Args:
        response: Full API response from ExecutionPlanRun

    Returns:
        Structured results dictionary with summary and test details
    """
    properties = response.get("properties", {})
    test_runs = properties.get("testRuns", [])
    provisioning_state = properties.get("provisioningState", "Unknown")

    # Initialize result structure
    results = {
        "timestamp": datetime.now().isoformat(),
        "provisioningState": provisioning_state,
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "criticalFailures": 0,
            "status": "Unknown"
        },
        "suites": {},
        "testRuns": []
    }

    # Process each test run
    for run in test_runs:
        test_name = run.get("testName", "Unknown")
        test_suite = run.get("testSuite", "Unknown")
        status = run.get("status", "Unknown")
        message = run.get("message", "")
        duration = run.get("durationInSeconds", 0)

        # Update counters
        results["summary"]["total"] += 1
        _increment_status_counter(results["summary"], status)

        # Track critical failures
        if status == STATUS_FAILED and test_suite in CRITICAL_SUITES:
            results["summary"]["criticalFailures"] += 1

        # Group by suite
        if test_suite not in results["suites"]:
            results["suites"][test_suite] = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "error": 0,
                "tests": []
            }

        suite = results["suites"][test_suite]
        suite["total"] += 1
        _increment_status_counter(suite, status)

        # Store test details
        test_detail = {
            "name": test_name,
            "suite": test_suite,
            "status": status,
            "message": message,
            "durationSeconds": duration,
            "isCritical": test_suite in CRITICAL_SUITES
        }
        suite["tests"].append(test_detail)
        results["testRuns"].append(test_detail)

    # Determine overall status
    if results["summary"]["criticalFailures"] > 0:
        results["summary"]["status"] = "Failed"
    elif results["summary"]["failed"] > 0:
        results["summary"]["status"] = "PassedWithWarnings"
    elif results["summary"]["error"] > 0:
        results["summary"]["status"] = "Error"
    elif results["summary"]["passed"] > 0:
        results["summary"]["status"] = "Passed"
    else:
        results["summary"]["status"] = "Unknown"

    return results


def generate_junit_xml(results: dict[str, Any]) -> str:
    """
    Generate JUnit XML format from validation results.

    This format is compatible with GitLab, Jenkins, and other CI/CD systems
    for test result visualization.

    Args:
        results: Parsed validation results

    Returns:
        JUnit XML as string
    """
    # Create root testsuites element
    testsuites = ET.Element("testsuites")
    testsuites.set("name", "Azure Compute Validation")
    testsuites.set("tests", str(results["summary"]["total"]))
    testsuites.set("failures", str(results["summary"]["failed"]))
    testsuites.set("errors", str(results["summary"]["error"]))
    testsuites.set("skipped", str(results["summary"]["skipped"]))
    testsuites.set("timestamp", results["timestamp"])

    # Create testsuite for each validation suite
    for suite_name, suite_data in results["suites"].items():
        testsuite = ET.SubElement(testsuites, "testsuite")
        testsuite.set("name", suite_name)
        testsuite.set("tests", str(suite_data["total"]))
        testsuite.set("failures", str(suite_data["failed"]))
        testsuite.set("errors", str(suite_data["error"]))
        testsuite.set("skipped", str(suite_data["skipped"]))

        # Add individual test cases
        for test in suite_data["tests"]:
            testcase = ET.SubElement(testsuite, "testcase")
            testcase.set("name", test["name"])
            testcase.set("classname", f"AzureComputeValidation.{suite_name}")
            testcase.set("time", str(test["durationSeconds"]))

            # Add failure/error/skipped elements based on status
            if test["status"] == STATUS_FAILED:
                failure = ET.SubElement(testcase, "failure")
                failure.set("message", test["message"] or "Test failed")
                failure.set("type", "AssertionError")
                if test["isCritical"]:
                    failure.text = f"CRITICAL: {test['message']}"
                else:
                    failure.text = test["message"]
            elif test["status"] == STATUS_ERROR:
                error = ET.SubElement(testcase, "error")
                error.set("message", test["message"] or "Test error")
                error.set("type", "RuntimeError")
                error.text = test["message"]
            elif test["status"] == STATUS_SKIPPED:
                skipped = ET.SubElement(testcase, "skipped")
                skipped.set("message", test["message"] or "Test skipped")

    # Pretty print the XML
    xml_str = ET.tostring(testsuites, encoding="unicode")
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ")


def print_summary(results: dict[str, Any]) -> None:
    """Print a human-readable summary of validation results."""
    summary = results["summary"]

    # Header and summary stats
    log("INFO", "=" * 50)
    log("INFO", "VALIDATION RESULTS SUMMARY")
    log("INFO", f"State: {results['provisioningState']} | Status: {summary['status']}")
    log("INFO", (f"Tests: {summary['passed']}/{summary['total']} passed, "
                 f"{summary['failed']} failed, {summary['skipped']} skipped"))
    if summary['criticalFailures'] > 0:
        log("WARNING", f"Critical Failures: {summary['criticalFailures']}")

    # Suite-level summary
    log("INFO", "-" * 50)
    for suite_name, suite_data in results["suites"].items():
        is_critical = suite_name in CRITICAL_SUITES
        marker = " [CRITICAL]" if is_critical else ""
        icon = "✓" if suite_data["failed"] == 0 and suite_data["error"] == 0 else "✗"
        log("INFO", f"  {icon} {suite_name}{marker}: {suite_data['passed']}/{suite_data['total']}")

    # Print failed tests
    failed_tests = [t for t in results["testRuns"] if t["status"] == STATUS_FAILED]
    if failed_tests:
        log("INFO", "-" * 50)
        log("INFO", "Failed Tests:")
        for test in failed_tests:
            marker = " [CRITICAL]" if test["isCritical"] else ""
            log("WARNING", f"  ✗ {test['name']}{marker}")
    log("INFO", "=" * 50)


def main() -> int:
    """
    Main entry point for the get results script.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # ==========================================================================
    # Argument Parsing
    # ==========================================================================
    parser = argparse.ArgumentParser(
        description="Retrieve Azure Compute Validation results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get results and save as JSON
  python3 get_results.py \\
    --subscription-id 12345678-1234-1234-1234-123456789abc \\
    --resource-group debian-validation-rg \\
    --cloud-validation debian-cv-123 \\
    --validation-execution-plan ep-bookworm-amd64-456 \\
    --execution-plan-run epr-789 \\
    --output-json results.json

  # Get results with JUnit output for CI/CD
  python3 get_results.py \\
    --subscription-id ... \\
    --resource-group ... \\
    --cloud-validation ... \\
    --validation-execution-plan ... \\
    --execution-plan-run ... \\
    --output-json results.json \\
    --output-junit results.junit.xml \\
    --fail-on-critical
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
        "--output-json",
        help="Path to write JSON results"
    )
    parser.add_argument(
        "--output-junit",
        help="Path to write JUnit XML results"
    )
    parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Exit with error code if critical tests fail"
    )
    parser.add_argument(
        "--fail-on-any",
        action="store_true",
        help="Exit with error code if any tests fail"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output"
    )

    args = parser.parse_args()

    # ==========================================================================
    # Execution
    # ==========================================================================
    try:
        if not args.quiet:
            log("INFO", "Azure Compute Validation - Get Results")

        # Build the resource URI
        uri = build_resource_uri(
            subscription_id=args.subscription_id,
            resource_group=args.resource_group,
            cloud_validation=args.cloud_validation,
            execution_plan=args.validation_execution_plan,
            execution_plan_run=args.execution_plan_run
        )

        # Fetch results
        if not args.quiet:
            log("INFO", "Fetching validation results...")

        with AzureClient() as client:
            response = get_execution_plan_run(uri, client)

        # Parse results
        results = parse_test_results(response)

        # Print summary
        if not args.quiet:
            print_summary(results)

        # Save JSON output
        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
            if not args.quiet:
                log("INFO", f"JSON results written to: {args.output_json}")

        # Save JUnit output
        if args.output_junit:
            junit_xml = generate_junit_xml(results)
            with open(args.output_junit, "w", encoding="utf-8") as f:
                f.write(junit_xml)
            if not args.quiet:
                log("INFO", f"JUnit XML written to: {args.output_junit}")

        # Determine exit code
        if args.fail_on_critical and results["summary"]["criticalFailures"] > 0:
            if not args.quiet:
                count = results['summary']['criticalFailures']
                log("ERROR", f"Exiting: {count} critical failure(s)")
            return 1

        if args.fail_on_any and results["summary"]["failed"] > 0:
            if not args.quiet:
                log("ERROR", f"Exiting: {results['summary']['failed']} test failure(s)")
            return 1

        return 0

    except RuntimeError as e:
        log("ERROR", f"Failed to get results: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
