import json
import re
from pathlib import Path


DEFAULT_ASSIGNMENT_NAME = "rg-tag-governance-audit"
DEFAULT_EFFECT = "Audit"
DEFAULT_EXCLUDED_RG_NAMES = []
DEFAULT_ALLOWED_ENVIRONMENT_VALUES = [
    "Production",
    "Development",
    "Test",
    "Sandbox",
]


class ConfigError(Exception):
    """Raised when a deployment configuration is not usable."""


def load_config(config_argument: str | None, project_root: Path) -> tuple[dict, Path]:
    config_path = (
        project_root / "config" / "sandbox.json"
        if config_argument is None
        else Path(config_argument)
    )
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config_path = config_path.resolve()

    if not config_path.is_file():
        raise ConfigError(f"Configuration file does not exist: {config_path}")

    try:
        with config_path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except json.JSONDecodeError as error:
        raise ConfigError(f"Configuration file is not valid JSON: {error.msg}") from error
    except OSError as error:
        raise ConfigError(f"Unable to read configuration file: {error}") from error

    if not isinstance(config, dict):
        raise ConfigError("Configuration must contain a JSON object")

    subscription_id = config.get("subscription_id")
    if not isinstance(subscription_id, str) or not subscription_id.strip():
        raise ConfigError("Configuration requires a non-empty 'subscription_id'")

    _validate_string(config, "initiative_assignment_name", required=False)
    _validate_string(config, "owner_domain", required=True)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", config["owner_domain"]):
        raise ConfigError("Configuration 'owner_domain' must be a lowercase domain without @")
    _validate_string_list(config, "excluded_rg_names")
    _validate_string_list(config, "rg_name_patterns", required=True)
    if len(config["rg_name_patterns"]) > 100:
        raise ConfigError("Configuration 'rg_name_patterns' cannot exceed 100 entries")
    _validate_string_list(config, "allowed_department_values", required=True)
    if len(config["allowed_department_values"]) > 100:
        raise ConfigError("Configuration 'allowed_department_values' cannot exceed 100 entries")
    _validate_string_list(config, "allowed_environment_values")
    if "effect" in config and config["effect"] != DEFAULT_EFFECT:
        raise ConfigError("Configuration 'effect' must be 'Audit'")

    return config, config_path


def assignment_settings(config: dict) -> dict:
    return {
        "assignment_name": config.get(
            "initiative_assignment_name", DEFAULT_ASSIGNMENT_NAME
        ),
        "effect": config.get("effect", DEFAULT_EFFECT),
        "excluded_rg_names": config.get(
            "excluded_rg_names", DEFAULT_EXCLUDED_RG_NAMES
        ),
        "owner_domain": config["owner_domain"],
        "rg_name_patterns": config["rg_name_patterns"],
        "allowed_department_values": config["allowed_department_values"],
        "allowed_environment_values": config.get(
            "allowed_environment_values", DEFAULT_ALLOWED_ENVIRONMENT_VALUES
        ),
    }


def _validate_string(config: dict, key: str, required: bool) -> None:
    if key not in config:
        if required:
            raise ConfigError(f"Configuration requires '{key}'")
        return
    if not isinstance(config[key], str) or not config[key].strip():
        raise ConfigError(f"Configuration '{key}' must be a non-empty string")


def _validate_string_list(config: dict, key: str, required: bool = False) -> None:
    if key not in config:
        if required:
            raise ConfigError(f"Configuration requires '{key}'")
        return
    values = config[key]
    if not isinstance(values, list) or (required and not values) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise ConfigError(f"Configuration '{key}' must be a non-empty list of strings")
