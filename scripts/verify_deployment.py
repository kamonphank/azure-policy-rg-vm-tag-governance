import argparse
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
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
        config, _ = load_config(args.config, project_root)
        settings = assignment_settings(config)
        subscription_id = config["subscription_id"]
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False
        )
        policy_client = PolicyClient(credential, subscription_id)
        checks = []

        for definition_name in POLICY_DEFINITION_NAMES:
            try:
                policy_client.policy_definitions.get(definition_name)
                _pass(checks, definition_name)
            except Exception:
                _fail(checks, definition_name)

        initiative = policy_client.policy_set_definitions.get(INITIATIVE_NAME)
        references = {
            _value(reference, "policy_definition_reference_id")
            for reference in (_value(_value(initiative, "properties"), "policy_definitions") or [])
        }
        expected_references = set(POLICY_DEFINITION_NAMES)
        _result(
            checks,
            "rg-tag-governance-initiative",
            references == expected_references,
        )

        scope = f"/subscriptions/{subscription_id}"
        assignment = policy_client.policy_assignments.get(
            scope, settings["assignment_name"]
        )
        assignment_properties = _value(assignment, "properties")
        expected_initiative_id = (
            f"{scope}/providers/Microsoft.Authorization/policySetDefinitions/"
            f"{INITIATIVE_NAME}"
        )
        _result(
            checks,
            settings["assignment_name"],
            _value(assignment_properties, "policy_definition_id").lower()
            == expected_initiative_id.lower(),
        )

        parameters = _value(assignment_properties, "parameters") or {}
        _result(checks, "effect = Audit", _parameter_value(parameters, "effect") == settings["effect"])
        _result(
            checks,
            "excludedRGNames matches config",
            _parameter_value(parameters, "excludedRGNames") == settings["excluded_rg_names"],
        )
        _result(checks, "ownerDomain matches config", _parameter_value(parameters, "ownerDomain") == settings["owner_domain"])
        _result(checks, "rgNamePatterns match config", _parameter_value(parameters, "rgNamePatterns") == settings["rg_name_patterns"])
        _result(
            checks,
            "allowedDepartmentValues match config",
            _parameter_value(parameters, "allowedDepartmentValues")
            == settings["allowed_department_values"],
        )
        _result(
            checks,
            "allowedEnvironmentValues match config",
            _parameter_value(parameters, "allowedEnvironmentValues")
            == settings["allowed_environment_values"],
        )

        print("\nOverall:")
        print("PASS" if all(checks) else "FAIL")
        return 0 if all(checks) else 1
    except (ConfigError, OSError, ValueError) as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1


def _value(resource, key):
    if isinstance(resource, dict):
        return resource.get(key)
    return getattr(resource, key, None)


def _parameter_value(parameters, key):
    parameter = parameters.get(key)
    return _value(parameter, "value") if parameter is not None else None


def _result(checks, label, passed):
    if passed:
        _pass(checks, label)
    else:
        _fail(checks, label)


def _pass(checks, label):
    checks.append(True)
    print(f"[PASS] {label}")


def _fail(checks, label):
    checks.append(False)
    print(f"[FAIL] {label}")


if __name__ == "__main__":
    raise SystemExit(main())
