import argparse
from importlib import import_module
import sys
from pathlib import Path

from config_utils import ConfigError, assignment_settings, load_config


STEPS = (
    ("deploy owner Policy Definition", "deploy.py"),
    ("deploy department Policy Definition", "deploy_department.py"),
    ("deploy environment Policy Definition", "deploy_environment.py"),
    ("deploy project Policy Definition", "deploy_project.py"),
    ("deploy Initiative", "deploy_initiative.py"),
    ("assign Initiative", "assign_initiative.py"),
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to the deployment configuration")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Execute the deployment sequence",
    )
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    try:
        config, config_path = load_config(args.config, project_root)
        settings = assignment_settings(config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1

    if not args.confirm:
        print("DRY RUN / PLAN ONLY\n")
        print("Config file:", config_path)
        print("Target subscription:", config["subscription_id"])
        print("Assignment name:", settings["assignment_name"])
        print("Effect:", settings["effect"])
        print("Owner domain:", settings["owner_domain"])
        print("RG name patterns:", settings["rg_name_patterns"])
        print("Allowed departments:", settings["allowed_department_values"])
        print("Deployment sequence:\n")
        _print_steps()
        print("\nNothing was deployed.")
        print("Re-run with --confirm to execute.")
        return 0

    print("Target subscription:", config["subscription_id"])
    print("Assignment name:", settings["assignment_name"])
    print("Effect:", settings["effect"])
    print("Config file:", config_path)
    print("Deployment sequence:\n")
    _print_steps()

    # Import/authenticate only after --confirm; dry-run remains offline.
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential(exclude_interactive_browser_credential=False) as credential:
        for step_name, script_name in STEPS:
            print(f"\n==> {step_name}")
            step = import_module(Path(script_name).stem)
            result = step.main(["--config", str(config_path)], credential=credential)
            if result != 0:
                print(f"Deployment stopped after failed step: {step_name}", file=sys.stderr)
                return result
    return 0


def _print_steps() -> None:
    for index, (step_name, _) in enumerate(STEPS, start=1):
        print(f"{index}. {step_name}")


if __name__ == "__main__":
    raise SystemExit(main())
