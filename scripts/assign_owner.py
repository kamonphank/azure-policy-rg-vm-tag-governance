import json
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.policy import PolicyClient
from config_utils import assignment_settings, load_config


POLICY_DEFINITION_NAME = "require-tag-owner"
NON_COMPLIANCE_MESSAGE = (
    "Resource Group or VM owner tag is missing or does not meet the required format. "
    "Each owner must use the configured lowercase domain with a nonempty local part and exactly one @. "
    "Separate owners with commas and no whitespace. Mailbox existence is not verified."
)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    config_path = project_root / "config" / "sandbox.json"

    try:
        config, _ = load_config(str(config_path), project_root)
        settings = assignment_settings(config)

        subscription_id = config["subscription_id"]
        assignment_name = config["owner_policy_assignment_name"]
        scope = f"/subscriptions/{subscription_id}"

        print(f"Authenticating to Azure for subscription {subscription_id}...")
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False
        )
        policy_client = PolicyClient(credential, subscription_id)

        print(f"Retrieving policy definition '{POLICY_DEFINITION_NAME}'...")
        definition = policy_client.policy_definitions.get(POLICY_DEFINITION_NAME)
        definition_id = definition.id or (
            f"{scope}/providers/Microsoft.Authorization/policyDefinitions/"
            f"{POLICY_DEFINITION_NAME}"
        )

        assignment = {
            "properties": {
                "displayName": "Require owner tag on resource groups (Audit)",
                "policyDefinitionId": definition_id,
                "parameters": {
                    "effect": {"value": "Audit"},
                    "excludedRGNames": {"value": []},
                    "ownerDomain": {"value": settings["owner_domain"]},
                    "rgNamePatterns": {"value": settings["rg_name_patterns"]},
                },
                "nonComplianceMessages": [
                    {"message": NON_COMPLIANCE_MESSAGE}
                ],
            }
        }

        print(f"Creating or updating policy assignment '{assignment_name}'...")
        result = policy_client.policy_assignments.create(
            scope,
            assignment_name,
            assignment,
        )
        print(f"Policy assignment deployed: {result.id}")
        return 0
    except (KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Policy assignment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
