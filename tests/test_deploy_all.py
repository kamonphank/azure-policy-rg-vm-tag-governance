"""Exercise the real six deployment steps with Azure clients replaced by mocks."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deploy_all
from config_utils import ConfigError, load_config


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / 'sandbox.json'
        self.config.write_text(json.dumps({
            'subscription_id': 'test-subscription',
            'owner_domain': 'example.com',
            'rg_name_patterns': ['R###RG??##'],
            'allowed_department_values': ['Engineering'],
        }))
        identity = ModuleType('azure.identity')
        identity.DefaultAzureCredential = MagicMock()
        policy = ModuleType('azure.mgmt.resource.policy')
        policy.PolicyClient = MagicMock()
        models = ModuleType('azure.mgmt.resource.policy.models')
        models.PolicyDefinition = MagicMock()
        self.factory = identity.DefaultAzureCredential
        self.client_factory = policy.PolicyClient
        self.client = self.client_factory.return_value
        modules_patch = patch.dict(sys.modules, {
            'azure.identity': identity,
            'azure.mgmt.resource.policy': policy,
            'azure.mgmt.resource.policy.models': models,
        })
        modules_patch.start()
        self.addCleanup(modules_patch.stop)
        self.output = io.StringIO()

    def run_deployment(self, confirm=True):
        args = ['--config', str(self.config)] + (['--confirm'] if confirm else [])
        with contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.output):
            return deploy_all.main(args)

    def test_all_six_steps_share_one_credential(self):
        self.assertEqual(self.run_deployment(), 0)
        self.factory.assert_called_once_with(exclude_interactive_browser_credential=False)
        credential = self.factory.return_value.__enter__.return_value
        self.assertEqual(self.client_factory.call_count, 6)
        for call in self.client_factory.call_args_list:
            self.assertIs(call.args[0], credential)
            self.assertEqual(call.args[1], 'test-subscription')
        self.assertEqual(self.client.policy_definitions.create_or_update.call_count, 4)
        self.client.policy_set_definitions.create_or_update.assert_called_once()
        self.client.policy_assignments.create.assert_called_once()
        assignment = self.client.policy_assignments.create.call_args.args[2]
        parameters = assignment['properties']['parameters']
        self.assertEqual(parameters['ownerDomain']['value'], 'example.com')
        self.assertEqual(parameters['rgNamePatterns']['value'], ['R###RG??##'])
        self.assertEqual(parameters['allowedDepartmentValues']['value'], ['Engineering'])
        self.factory.return_value.__exit__.assert_called_once()

    def test_dry_run_never_authenticates_or_deploys(self):
        self.assertEqual(self.run_deployment(confirm=False), 0)
        self.factory.assert_not_called()
        self.client_factory.assert_not_called()

    def test_missing_company_specific_settings_fail_before_deploy(self):
        self.config.write_text(json.dumps({'subscription_id': 'test-subscription'}))
        with self.assertRaises(ConfigError):
            load_config(str(self.config), Path(__file__).resolve().parents[1])
        self.assertEqual(self.run_deployment(), 1)
        self.factory.assert_not_called()

    def test_failure_stops_later_steps_and_closes_shared_credential(self):
        self.client.policy_definitions.create_or_update.side_effect = [MagicMock(), RuntimeError('rejected')]
        self.assertEqual(self.run_deployment(), 1)
        self.assertEqual(self.client.policy_definitions.create_or_update.call_count, 2)
        self.client.policy_set_definitions.create_or_update.assert_not_called()
        self.client.policy_assignments.create.assert_not_called()
        self.factory.return_value.__exit__.assert_called_once()

    def test_standalone_step_still_creates_its_own_credential(self):
        step = deploy_all.import_module('deploy')
        with contextlib.redirect_stdout(self.output):
            self.assertEqual(step.main(['--config', str(self.config)]), 0)
        self.factory.assert_called_once()
        self.assertIs(self.client_factory.call_args.args[0], self.factory.return_value)
