import json
import argparse
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.policy import PolicyClient
from azure.mgmt.resource.policy.models import PolicyDefinition

from config_utils import ConfigError, load_config


POLICY_DEFINITION_NAME = "require-tag-project"


def main(argv=None, *, credential=None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    policy_path = project_root / "policies" / "require-tag-project.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to the deployment configuration")
    args = parser.parse_args(argv)

    try:
        config, _ = load_config(args.config, project_root)
        subscription_id = config["subscription_id"]

        with policy_path.open(encoding="utf-8") as policy_file:
            policy_document = json.load(policy_file)
        policy_properties = policy_document["properties"]

        if credential is None:
            print(f"Authenticating to Azure for subscription {subscription_id}...")
            credential = DefaultAzureCredential(
                exclude_interactive_browser_credential=False
            )
        policy_client = PolicyClient(credential, subscription_id)

        policy_definition = PolicyDefinition(
            display_name=policy_properties["displayName"],
            policy_type=policy_properties["policyType"],
            mode=policy_properties["mode"],
            description=policy_properties.get("description"),
            metadata=policy_properties.get("metadata"),
            parameters=policy_properties.get("parameters"),
            policy_rule=policy_properties["policyRule"],
        )

        print(f"Creating or updating policy definition '{POLICY_DEFINITION_NAME}'...")
        result = policy_client.policy_definitions.create_or_update(
            POLICY_DEFINITION_NAME,
            policy_definition,
        )
        print(f"Policy definition deployed: {result.id}")
        print("No policy assignment was created.")
        return 0
    except (ConfigError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Configuration or policy file error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Azure deployment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
