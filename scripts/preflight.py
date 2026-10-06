import argparse
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.subscriptions import SubscriptionClient
from azure.mgmt.resource.policy import PolicyClient

from config_utils import ConfigError, assignment_settings, load_config


INITIATIVE_NAME = "rg-tag-governance-initiative"
POLICY_DEFINITION_NAMES = (
    "require-tag-owner",
    "require-tag-department",
    "require-tag-environment",
    "require-tag-project",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to the deployment configuration")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]

    try:
        config, config_path = load_config(args.config, project_root)
        settings = assignment_settings(config)
        subscription_id = config["subscription_id"]
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False
        )
        subscription = SubscriptionClient(credential).subscriptions.get(subscription_id)
        policy_client = PolicyClient(credential, subscription_id)

        print("=== RG Tag Governance Preflight ===")
        print(f"\nConfig:\n{config_path}")
        print(f"\nSubscription:\n{subscription.display_name}")
        print(f"Subscription ID:\n{_mask_subscription_id(subscription_id)}")
        print(f"\nAssignment:\n{settings['assignment_name']}")
        print(f"Effect:\n{settings['effect']}")
        print(f"Owner domain:\n{settings['owner_domain']}")
        print(f"RG name patterns:\n{settings['rg_name_patterns']}")
        print(f"Excluded RG names:\n{settings['excluded_rg_names']}")
        print(f"Department allowed values:\n{settings['allowed_department_values']}")
        print(f"Environment allowed values:\n{settings['allowed_environment_values']}")
        print("\nPlanned architecture:\n")
        print("Subscription")
        print(f"  -> {settings['assignment_name']}")
        print(f"  -> {INITIATIVE_NAME}")
        print("  -> 4 Policy Definitions")

        next(iter(policy_client.policy_definitions.list()), None)
        next(
            iter(policy_client.policy_assignments.list()),
            None,
        )
        print("\nRead access: Policy definitions and assignments can be queried.")
        print("\nNO CHANGES WERE MADE.")
        return 0
    except (ConfigError, OSError, ValueError) as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Preflight read check failed: {error}", file=sys.stderr)
        return 1


def _mask_subscription_id(subscription_id: str) -> str:
    if len(subscription_id) <= 8:
        return subscription_id
    return f"...{subscription_id[-8:]}"


if __name__ == "__main__":
    raise SystemExit(main())
