"""Safely remove the RG/VM fixtures created by create_vm_tag_test_fixtures.py.

Default behavior is a dry run. Nothing is deleted without --confirm.

The normal cleanup removes only the eight exact fixture Resource Groups. That
also removes their VMs, NICs, VNets, subnets and managed disks. It does not
touch unrelated resources in the subscription.

The fixture creator also updates subscription-level Policy Definitions,
Initiative and Assignment. Those are intentionally NOT removed by default,
because they may have existed before the fixture run or may be used elsewhere.
Use --delete-policy only when this Sandbox policy deployment is disposable and
you have confirmed that no other assignment depends on these definitions.

Use --vm RG/VM for the Azure for Students workflow. It deletes only that VM
and its managed OS disk, leaving the RG and shared test network in place for
the next fixture. The default remains a dry run.

Examples (PowerShell):

    python scripts/cleanup_vm_tag_test_fixtures.py
    python scripts/cleanup_vm_tag_test_fixtures.py --confirm
    python scripts/cleanup_vm_tag_test_fixtures.py --confirm --delete-policy
"""

import argparse
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource.policy import PolicyClient
from azure.mgmt.resource.resources import ResourceManagementClient

from config_utils import ConfigError, assignment_settings, load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_RESOURCE_GROUPS = (
    "R901RGAA01",
    "R901RGAA02",
    "R901RGAA03",
    "R901RGAA04",
    "R901RGAA05",
    "R901RGAA06",
    "unmanaged-rg",
    "R901RGAA08",
)
POLICY_DEFINITIONS = (
    "require-tag-owner",
    "require-tag-department",
    "require-tag-environment",
    "require-tag-project",
)
INITIATIVE_NAME = "rg-tag-governance-initiative"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Sandbox configuration path")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete selected resources; without it this is a dry run",
    )
    parser.add_argument(
        "--delete-policy",
        action="store_true",
        help="Also delete the fixture assignment, initiative and four definitions",
    )
    parser.add_argument(
        "--vm",
        action="append",
        metavar="RG/VM",
        help="Delete only this fixture VM and its managed OS disk; repeat as needed",
    )
    return parser.parse_args()


def delete_policy_resources(policy_client: PolicyClient, scope: str, assignment_name: str) -> None:
    print(f"Deleting policy assignment '{assignment_name}'...")
    policy_client.policy_assignments.delete(scope, assignment_name)

    print(f"Deleting initiative '{INITIATIVE_NAME}'...")
    policy_client.policy_set_definitions.delete(INITIATIVE_NAME)

    for definition_name in POLICY_DEFINITIONS:
        print(f"Deleting policy definition '{definition_name}'...")
        policy_client.policy_definitions.delete(definition_name)


def parse_vm_names(values: list[str] | None) -> list[tuple[str, str]]:
    parsed = []
    for value in values or []:
        group_name, separator, vm_name = value.partition("/")
        if not separator or not group_name or not vm_name:
            raise ConfigError(f"VM must use RG/VM format: {value}")
        parsed.append((group_name, vm_name))
    return parsed


def main() -> int:
    args = parse_args()
    try:
        config, config_path = load_config(args.config, PROJECT_ROOT)
        fixture_resource_groups = config.get("fixture_resource_group_names", FIXTURE_RESOURCE_GROUPS)
        if not isinstance(fixture_resource_groups, (list, tuple)) or not fixture_resource_groups or not all(
            isinstance(name, str) and name.strip() for name in fixture_resource_groups
        ):
            raise ConfigError("fixture_resource_group_names must be a non-empty list of names")
        subscription_id = config["subscription_id"]
        scope = f"/subscriptions/{subscription_id}"
        vm_names = parse_vm_names(args.vm)
        if vm_names and args.delete_policy:
            raise ConfigError("--vm cannot be combined with --delete-policy")
        mode = "DELETE MODE" if args.confirm else "DRY RUN"

        print(f"Using configuration: {config_path}")
        print(f"Mode: {mode}")
        if vm_names:
            print("VMs selected:")
            for group_name, vm_name in vm_names:
                print(f"- {group_name}/{vm_name}")
        else:
            print("Resource Groups selected:")
            for group_name in fixture_resource_groups:
                print(f"- {group_name}")
        print(f"Policy cleanup requested: {'yes' if args.delete_policy else 'no'}")

        if not args.confirm:
            print("Nothing was deleted. Re-run with --confirm after reviewing the list.")
            return 0

        with DefaultAzureCredential(exclude_interactive_browser_credential=False) as credential:
            if vm_names:
                compute_client = ComputeManagementClient(credential, subscription_id)
                for group_name, vm_name in vm_names:
                    vm = compute_client.virtual_machines.get(group_name, vm_name)
                    managed_disk = getattr(
                        getattr(getattr(vm, "storage_profile", None), "os_disk", None),
                        "managed_disk",
                        None,
                    )
                    disk_id = getattr(managed_disk, "id", None)
                    print(f"Deleting VM '{group_name}/{vm_name}'...")
                    compute_client.virtual_machines.begin_delete(group_name, vm_name).result()
                    if disk_id:
                        disk_name = disk_id.rsplit("/", 1)[-1]
                        print(f"Deleting managed OS disk '{disk_name}'...")
                        compute_client.disks.begin_delete(group_name, disk_name).result()
            else:
                resource_client = ResourceManagementClient(credential, subscription_id)
                for group_name in fixture_resource_groups:
                    print(f"Deleting Resource Group '{group_name}'...")
                    resource_client.resource_groups.begin_delete(group_name).result()
                    print(f"Deleted Resource Group '{group_name}'.")

            if args.delete_policy:
                policy_client = PolicyClient(credential, subscription_id)
                delete_policy_resources(policy_client, scope, assignment_settings(config)["assignment_name"])

        print("Cleanup completed.")
        return 0
    except (ConfigError, OSError, ValueError) as error:
        print(f"Cleanup setup error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Cleanup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
