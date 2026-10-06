import copy
import argparse
import json
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.policy import PolicyClient

from config_utils import ConfigError, load_config


INITIATIVE_NAME = "rg-tag-governance-initiative"
POLICY_DEFINITION_NAMES = (
    "require-tag-owner",
    "require-tag-department",
    "require-tag-environment",
    "require-tag-project",
)


def main(argv=None, *, credential=None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    initiative_path = project_root / "initiative" / "rg-tag-governance-initiative.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to the deployment configuration")
    args = parser.parse_args(argv)

    try:
        config, _ = load_config(args.config, project_root)
        subscription_id = config["subscription_id"]

        with initiative_path.open(encoding="utf-8") as initiative_file:
            initiative_document = json.load(initiative_file)

        if credential is None:
            print(f"Authenticating to Azure for subscription {subscription_id}...")
            credential = DefaultAzureCredential(
                exclude_interactive_browser_credential=False
            )
        policy_client = PolicyClient(credential, subscription_id)
        scope = f"/subscriptions/{subscription_id}"

        definition_ids = {}
        for definition_name in POLICY_DEFINITION_NAMES:
            print(f"Retrieving policy definition '{definition_name}'...")
            definition = policy_client.policy_definitions.get(definition_name)
            definition_ids[definition_name] = definition.id or (
                f"{scope}/providers/Microsoft.Authorization/policyDefinitions/"
                f"{definition_name}"
            )

        initiative = copy.deepcopy(initiative_document["properties"])
        for policy_definition in initiative["policyDefinitions"]:
            reference_id = policy_definition["policyDefinitionReferenceId"]
            policy_definition["policyDefinitionId"] = definition_ids[reference_id]

        print(f"Creating or updating policy set definition '{INITIATIVE_NAME}'...")
        result = policy_client.policy_set_definitions.create_or_update(
            INITIATIVE_NAME,
            {"properties": initiative},
        )
        print(f"Initiative deployed: {result.id}")
        print("No policy assignment was created.")
        return 0
    except (ConfigError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Configuration or initiative file error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Azure initiative deployment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())