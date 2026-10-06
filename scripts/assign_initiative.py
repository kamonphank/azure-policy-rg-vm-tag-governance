import json
import argparse
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.policy import PolicyClient

from config_utils import ConfigError, assignment_settings, load_config


INITIATIVE_NAME = "rg-tag-governance-initiative"
NON_COMPLIANCE_MESSAGES = [
    {
        "policyDefinitionReferenceId": "require-tag-department",
        "message": "department is missing or must exactly match an allowed department value, including case.",
    },
    {
        "policyDefinitionReferenceId": "require-tag-environment",
        "message": "environment is missing or must exactly match Production, Development, Test, or Sandbox.",
    },
    {
        "policyDefinitionReferenceId": "require-tag-project",
        "message": "project is missing or must use comma-separated values without spaces around commas.",
    },
]


def main(argv=None, *, credential=None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to the deployment configuration")
    args = parser.parse_args(argv)

    try:
        config, _ = load_config(args.config, project_root)
        settings = assignment_settings(config)
        messages = [{
            "policyDefinitionReferenceId": "require-tag-owner",
            "message": (
                "owner must be one or more lowercase addresses ending in "
                f"@{settings['owner_domain']}, separated by commas."
            ),
        }, *NON_COMPLIANCE_MESSAGES]
        subscription_id = config["subscription_id"]
        scope = f"/subscriptions/{subscription_id}"
        initiative_id = (
            f"{scope}/providers/Microsoft.Authorization/policySetDefinitions/"
            f"{INITIATIVE_NAME}"
        )

        if credential is None:
            print(f"Authenticating to Azure for subscription {subscription_id}...")
            credential = DefaultAzureCredential(
                exclude_interactive_browser_credential=False
            )
        policy_client = PolicyClient(credential, subscription_id)

        assignment = {
            "properties": {
                "displayName": "RG and VM Tag Governance Initiative (Audit)",
                "policyDefinitionId": initiative_id,
                "parameters": {
                    "effect": {"value": settings["effect"]},
                    "excludedRGNames": {"value": settings["excluded_rg_names"]},
                    "ownerDomain": {"value": settings["owner_domain"]},
                    "rgNamePatterns": {"value": settings["rg_name_patterns"]},
                    "allowedDepartmentValues": {
                        "value": settings["allowed_department_values"]
                    },
                    "allowedEnvironmentValues": {
                        "value": settings["allowed_environment_values"]
                    },
                },
                "nonComplianceMessages": messages,
            }
        }

        print(
            f"Creating or updating policy assignment "
            f"'{settings['assignment_name']}'..."
        )
        result = policy_client.policy_assignments.create(
            scope,
            settings["assignment_name"],
            assignment,
        )
        print(f"Policy assignment deployed: {result.id}")
        return 0
    except (ConfigError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Initiative assignment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
