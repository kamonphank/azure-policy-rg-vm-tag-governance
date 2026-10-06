"""Create the Sandbox RG/VM fixtures used by the RG and VM tag test matrix.

PREREQUISITES
-------------
1. Install dependencies from requirements.txt and authenticate with an identity
   that can deploy Policy Definitions/Initiatives/Assignments, create RGs and
   create/start/deallocate VMs in the Sandbox subscription.
2. Review config/sandbox.json. The script uses its subscription_id and location.
3. Ensure an SSH public key exists at ~/.ssh/id_rsa.pub, or pass
    --ssh-key-path with another public-key path. For example, on PowerShell:
    ssh-keygen -t ed25519 -f "$HOME/.ssh/id_rsa" and press Enter twice when
    prompted for an empty passphrase.
4. Run this script from the repository root, or pass --config with a path to a
    Sandbox configuration file.

For the first run, let the script deploy the current policies. For subsequent
one-VM test cycles, add --skip-policy-deploy to avoid repeating that step:

    python scripts/create_vm_tag_test_fixtures.py --fixture R901RGAA01/vm-valid-01 --vm-size Standard_D2s_v3 --zone 3
    python scripts/create_vm_tag_test_fixtures.py --fixture R901RGAA02/vm-missing-tags --vm-size Standard_D2s_v3 --zone 3 --skip-policy-deploy

EXAMPLE COMMAND
---------------
Select an available x64 SKU in the Azure Portal, then run for example:

    python scripts/create_vm_tag_test_fixtures.py --vm-size Standard_D2s_v3 --zone 3

Do not copy that SKU blindly: capacity can change. The VM image below is x64,
so choose an x64 SKU. If the Portal shows an Arm64-only SKU such as a `D2ps`
variant, the image reference must also be changed to an Arm64 Ubuntu image.

The script updates all four Policy Definitions, the Initiative, and the Audit
assignment before creating resources. This keeps the fixtures aligned with the
current files in policies/ and initiative/. It does not enable Deny.

FIXTURES
--------
8 Resource Groups and 11 VMs are created or updated:

- R901RGAA01 / vm-valid-01: valid RG and VM baseline.
- R901RGAA02 / vm-missing-tags: valid RG; VM has no required tags.
- R901RGAA03 / vm-valid-tags: RG has no tags; VM has all valid tags.
- R901RGAA04 / vm-owner, vm-department, vm-environment, vm-project:
  one VM per invalid tag policy, while the RG remains valid.
- R901RGAA05 / vm-owner-domain: owner-domain cases are tested by changing
  this VM's owner tag between scans.
- R901RGAA06 / vm-owner-format: malformed owner-list cases are tested by
  changing this VM's owner tag between scans.
- unmanaged-rg / R901RGAA99: neither the RG name nor its parent scope matches;
  this proves that a VM name cannot bring its parent RG into scope.
- R901RGAA08 / vm-excluded: exclusion behavior is tested by adding/removing
  R901RGAA08 from excluded_rg_names and redeploying the assignment.

VMs default to Standard_B1s, but availability is region/capacity dependent.
Use --vm-size to select an available low-cost SKU when B1s is unavailable.
The default availability zone is 3; use --zone to select one supported by your region.
Each VM gets a private-only NIC (no Public IP) and is
deallocated after creation, so compute billing stops; managed OS disks may
still incur charges. The script does not delete resources. Use
cleanup_vm_tag_test_fixtures.py only after reviewing its safety selection, or delete these
named RGs explicitly.

After this script completes, trigger a policy scan and query each result by
(resource_id, policy_definition_reference_id). The script only provisions
fixtures; it does not claim that Azure compliance results have propagated.
"""

import argparse
import sys
import time
from importlib import import_module
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import HardwareProfile, LinuxConfiguration, NetworkInterfaceReference, NetworkProfile, OSProfile, OSDisk, SshConfiguration, SshPublicKey, StorageProfile, VirtualMachine
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import AddressSpace, NetworkInterface, NetworkInterfaceIPConfiguration, SubResource, Subnet, VirtualNetwork
from azure.mgmt.resource.resources import ResourceManagementClient

from config_utils import ConfigError, load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VM_SIZE = "Standard_B1s"
DEFAULT_QUOTA_WAIT_SECONDS = 0
VM_IMAGE = {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts-gen2", "version": "latest"}
ADMIN_USERNAME = "azureuser"
SSH_INSTALL_PATH = "/home/azureuser/.ssh/authorized_keys"
VNET_NAME = "vm-tag-test-vnet"
SUBNET_NAME = "vm-tag-test-subnet"

def build_fixtures(config: dict) -> tuple[dict, list[tuple]]:
    if "R###RG??##" not in config["rg_name_patterns"]:
        raise ConfigError("Sandbox fixtures require R###RG??## in rg_name_patterns")
    valid_tags = {
        "owner": f"alice@{config['owner_domain']},bob@{config['owner_domain']}",
        "department": config["allowed_department_values"][0],
        "environment": config.get("allowed_environment_values", ["Sandbox"])[-1],
        "project": "Project-A,Project-B",
    }
    invalid_department = valid_tags["department"].lower()
    if invalid_department == valid_tags["department"]:
        invalid_department = "not-an-allowed-department"
    fixtures = [
        ("R901RGAA01", [("vm-valid-01", valid_tags)]),
        ("R901RGAA02", [("vm-missing-tags", {})]),
        ("R901RGAA03", [("vm-valid-tags", valid_tags)], {}),
        ("R901RGAA04", [
            ("vm-owner", {**valid_tags, "owner": "alice@invalid.example"}),
            ("vm-department", {**valid_tags, "department": invalid_department}),
            ("vm-environment", {**valid_tags, "environment": "not-an-allowed-environment"}),
            ("vm-project", {**valid_tags, "project": "Project-A, Project-B"}),
        ]),
        ("R901RGAA05", [("vm-owner-domain", valid_tags)]),
        ("R901RGAA06", [("vm-owner-format", valid_tags)]),
        ("unmanaged-rg", [("R901RGAA99", {})]),
        ("R901RGAA08", [("vm-excluded", {})]),
    ]
    return valid_tags, fixtures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Sandbox configuration path")
    parser.add_argument(
        "--skip-policy-deploy",
        action="store_true",
        help="Skip policy/initiative/assignment deployment; use after the first run",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        metavar="RG/VM",
        help=(
            "Create only the named VM fixture; repeat for multiple fixtures. "
            "Example: --fixture R901RGAA01/vm-valid-01"
        ),
    )
    parser.add_argument(
        "--ssh-key-path",
        default="~/.ssh/id_rsa.pub",
        help="SSH public key path used by the Linux VMs (default: ~/.ssh/id_rsa.pub)",
    )
    parser.add_argument(
        "--vm-size",
        default=DEFAULT_VM_SIZE,
        help=(
            f"Azure VM size (default: {DEFAULT_VM_SIZE}). "
            "Use an available x64 SKU, for example Standard_D2s_v3."
        ),
    )
    parser.add_argument(
        "--zone",
        default="3",
        help="Availability zone for every VM (default: 3)",
    )
    parser.add_argument(
        "--quota-wait-seconds",
        type=int,
        default=DEFAULT_QUOTA_WAIT_SECONDS,
        help=(
            "Optional seconds to wait for regional quota propagation after "
            f"deallocation (default: {DEFAULT_QUOTA_WAIT_SECONDS})"
        ),
    )
    return parser.parse_args()


DEPLOYMENT_STEPS = (
    "deploy",
    "deploy_department",
    "deploy_environment",
    "deploy_project",
    "deploy_initiative",
    "assign_initiative",
)


def deploy_current_policy(config_path: Path, credential) -> None:
    """Deploy the repository's four definitions, initiative and Audit assignment."""
    for module_name in DEPLOYMENT_STEPS:
        print(f"Updating policy component: {module_name}...")
        module = import_module(module_name)
        result = module.main(["--config", str(config_path)], credential=credential)
        if result != 0:
            raise RuntimeError(
                f"Policy deployment failed at {module_name}; VM fixtures were not created"
            )


def public_key(key_path_value: str) -> str:
    key_path = Path(key_path_value).expanduser()
    if not key_path.is_file():
        raise ConfigError(
            f"SSH public key not found: {key_path}. "
            "Create one with 'ssh-keygen -t ed25519' or pass --ssh-key-path."
        )
    return key_path.read_text(encoding="utf-8").strip()


def vm_model(
    location: str,
    tags: dict[str, str],
    key: str,
    nic_id: str,
    vm_size: str,
    zone: str,
) -> VirtualMachine:
    return VirtualMachine(
        location=location,
        zones=[zone],
        tags=tags,
        hardware_profile=HardwareProfile(vm_size=vm_size),
        network_profile=NetworkProfile(
            network_interfaces=[NetworkInterfaceReference(id=nic_id, primary=True)]
        ),
        storage_profile=StorageProfile(
            image_reference=VM_IMAGE,
            os_disk=OSDisk(create_option="FromImage", name=None),
        ),
        os_profile=OSProfile(
            computer_name="testvm",
            admin_username=ADMIN_USERNAME,
            linux_configuration=LinuxConfiguration(
                disable_password_authentication=True,
                ssh=SshConfiguration(
                    public_keys=[SshPublicKey(path=SSH_INSTALL_PATH, key_data=key)]
                ),
            ),
        ),
    )


def create_network(network_client, group_name: str, location: str, vm_name: str) -> str:
    """Create/reuse a private-only VNet, subnet and NIC for one fixture VM."""
    network_client.virtual_networks.begin_create_or_update(
        group_name,
        VNET_NAME,
        VirtualNetwork(
            location=location,
            address_space=AddressSpace(address_prefixes=["10.250.0.0/16"]),
        ),
    ).result()
    subnet = network_client.subnets.begin_create_or_update(
        group_name,
        VNET_NAME,
        SUBNET_NAME,
        Subnet(address_prefix="10.250.0.0/24"),
    ).result()
    nic = network_client.network_interfaces.begin_create_or_update(
        group_name,
        f"{vm_name}-nic",
        NetworkInterface(
            location=location,
            ip_configurations=[
                NetworkInterfaceIPConfiguration(
                    name="ipconfig1",
                    private_ip_allocation_method="Dynamic",
                    subnet=SubResource(id=subnet.id),
                )
            ],
        ),
    ).result()
    return nic.id


def create_fixture_resources(
    config: dict,
    credential,
    ssh_key_path: str,
    vm_size: str,
    zone: str,
    quota_wait_seconds: int,
    fixture_names: list[str] | None,
) -> None:
    subscription_id = config["subscription_id"]
    location = config["location"]
    resource_client = ResourceManagementClient(credential, subscription_id)
    compute_client = ComputeManagementClient(credential, subscription_id)
    network_client = NetworkManagementClient(credential, subscription_id)
    key = public_key(ssh_key_path)

    valid_tags, fixtures = build_fixtures(config)
    selected_fixtures = select_fixtures(fixture_names, fixtures)
    for group_name, vm_specs, *optional_tags in selected_fixtures:
        rg_tags = optional_tags[0] if optional_tags else ({} if group_name in {"R901RGAA03", "unmanaged-rg"} else valid_tags)
        print(f"Creating or updating Resource Group '{group_name}'...")
        resource_client.resource_groups.create_or_update(group_name, {"location": location, "tags": rg_tags})
        for vm_name, tags in vm_specs:
            print(f"Creating or updating VM '{group_name}/{vm_name}' ({vm_size})...")
            nic_id = create_network(network_client, group_name, location, vm_name)
            model = vm_model(location, tags, key, nic_id, vm_size, zone)
            compute_client.virtual_machines.begin_create_or_update(group_name, vm_name, model).result()
            print(f"Deallocating VM '{group_name}/{vm_name}'...")
            compute_client.virtual_machines.begin_deallocate(group_name, vm_name).result()
            if quota_wait_seconds > 0:
                wait_for_quota_release(quota_wait_seconds)


def select_fixtures(fixture_names: list[str] | None, fixtures: list[tuple]) -> list[tuple]:
    if not fixture_names:
        return fixtures
    requested = set(fixture_names)
    selected = []
    known = set()
    for group_name, vm_specs, *optional_tags in fixtures:
        remaining = []
        for vm_name, tags in vm_specs:
            key = f"{group_name}/{vm_name}"
            known.add(key)
            if key in requested:
                remaining.append((vm_name, tags))
        if remaining:
            selected.append((group_name, remaining, *optional_tags))
    unknown = requested - known
    if unknown:
        raise ConfigError(
            "Unknown fixture(s): " + ", ".join(sorted(unknown))
        )
    return selected


def wait_for_quota_release(wait_seconds: int) -> None:
    """Allow Azure time to propagate deallocation before the next create."""
    if wait_seconds <= 0:
        return
    print(
        f"Waiting {wait_seconds} seconds for Azure quota propagation "
        "before the next VM..."
    )
    time.sleep(wait_seconds)


def main() -> int:
    args = parse_args()
    try:
        config, config_path = load_config(args.config, PROJECT_ROOT)
        print(f"Using configuration: {config_path}")
        with DefaultAzureCredential(exclude_interactive_browser_credential=False) as credential:
            if args.skip_policy_deploy:
                print("Skipping policy deployment; using the existing assignment.")
            else:
                deploy_current_policy(config_path, credential)
            create_fixture_resources(
                config,
                credential,
                args.ssh_key_path,
                args.vm_size,
                args.zone,
                args.quota_wait_seconds,
                args.fixture,
            )
        print("\nFixture creation completed. All VMs were deallocated.")
        print("Next: trigger a Policy scan and wait for Policy Insights propagation.")
        return 0
    except (ConfigError, OSError, ValueError) as error:
        print(f"Fixture setup error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Fixture creation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
