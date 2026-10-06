import json
import copy
from pathlib import Path
import unittest

from policy_evaluator import PolicyEvaluator, validate_count_sources


ROOT = Path(__file__).resolve().parents[1]
RG = 'Microsoft.Resources/subscriptions/resourceGroups'
VM = 'Microsoft.Compute/virtualMachines'
VALID = {
    'owner': 'alice@example.com,bob@example.com',
    'department': 'Engineering',
    'environment': 'Sandbox',
    'project': 'Project Alpha,Project Beta',
}
POLICIES = {
    path.stem.removeprefix('require-tag-'): json.loads(path.read_text())['properties']
    for path in (ROOT / 'policies').glob('*.json')
}


def violation(tag, resource, **parameters):
    policy = POLICIES[tag]
    evaluator = PolicyEvaluator(policy, resource, parameters)
    return evaluator.condition(policy['policyRule']['if'])


def resource(kind, tags=None, group='R123RGAB01', name=None):
    result = {'type': kind, 'name': name or (group if kind == RG else 'vm-any-name'),
              'tags': dict(VALID if tags is None else tags)}
    if kind != RG:
        result['resourceGroup'] = group
    return result


class PolicyRulesTests(unittest.TestCase):
    def test_count_sources_do_not_depend_on_resource_fields(self):
        for policy in POLICIES.values():
            validate_count_sources(policy['policyRule'])

    def test_reject_reported_invalid_count_expression(self):
        broken = copy.deepcopy(POLICIES['owner'])
        broken['policyRule']['if'] = {
            'count': {'value': "[take(split(string(coalesce(field('tags[owner]'), '')), ','), 100)]"},
            'greater': 0,
        }
        with self.assertRaisesRegex(ValueError, 'count.value must not contain field'):
            PolicyEvaluator(broken, resource(VM))

    def test_all_tags_on_rg_and_vm(self):
        for kind in (RG, VM):
            for tag in POLICIES:
                for value in ('valid', 'missing', 'empty', 'invalid'):
                    with self.subTest(kind=kind, tag=tag, value=value):
                        tags = dict(VALID)
                        if value == 'missing':
                            del tags[tag]
                        elif value != 'valid':
                            tags[tag] = '' if value == 'empty' else {
                                'owner': 'a@gmail.com', 'department': 'Finance',
                                'environment': 'sandbox', 'project': 'Project A, B',
                            }[tag]
                        self.assertEqual(violation(tag, resource(kind, tags)), value != 'valid')

    def test_scope_patterns_and_exclusions_apply_to_parent_rg(self):
        for tag in POLICIES:
            for kind in (RG, VM):
                for group in ('R123RGAB01', 'R999RGZZ99', 'R000RGAA00'):
                    with self.subTest(tag=tag, kind=kind, group=group):
                        obj = resource(kind, {}, group)
                        self.assertTrue(violation(tag, obj))
                        self.assertFalse(violation(tag, obj, excludedRGNames=[group.lower()]))
                        self.assertTrue(violation(tag, obj, excludedRGNames=['another-rg']))
                for group in ('unmanaged', 'r123RGAB01', 'R12RGAB01', 'R123RG1234'):
                    # A VM name matching the RG pattern must not bring its parent into scope.
                    obj = resource(kind, {}, group, 'R123RGAB01' if kind == VM else group)
                    self.assertFalse(violation(tag, obj))

    def test_other_resource_types_and_subscription_are_not_targeted(self):
        for tag in POLICIES:
            for kind in ('Microsoft.Network/networkInterfaces',
                         'Microsoft.Compute/virtualMachineScaleSets',
                         'Microsoft.Compute/virtualMachines/extensions',
                         'Microsoft.Resources/subscriptions'):
                obj = {'type': kind, 'name': 'R123RGAB01', 'tags': {}}
                self.assertFalse(violation(tag, obj))

    def test_vm_tags_are_independent_from_rg_tags(self):
        for tag in POLICIES:
            self.assertFalse(violation(tag, resource(RG)))
            self.assertTrue(violation(tag, resource(VM, {})))
            self.assertTrue(violation(tag, resource(RG, {})))
            self.assertFalse(violation(tag, resource(VM)))

    def test_owner_list_domain_and_malformed_values(self):
        valid = ('a@example.com', 'a+b@example.com',
                 'a@example.com,b@example.com')
        invalid = ('', 'a', '@example.com', 'a@@example.com',
               'a@EXAMPLE.COM', 'a@Example.Com',
                   'a@example.com@example.com', 'a@gmail.com',
                   'a@sub.example.com', 'a@example.com.evil', 'a@notexample.com',
                   'a@exampleXcom',
                   'a@example.com,b@gmail.com', 'a@gmail.com,b@example.com',
                   'a@example.com,b', 'a@example.com,@example.com',
                   ',a@example.com', 'a@example.com,', 'a@example.com,,b@example.com',
                   ' a@example.com', 'a@example.com ', 'a@example.com, b@example.com',
                   'a\tb@example.com', 'a@example.com\n', 'a\r@example.com',
                   ',' * 511)
        for kind in (RG, VM):
            for owner in valid + invalid:
                with self.subTest(kind=kind, owner=owner):
                    self.assertEqual(violation('owner', resource(kind, {'owner': owner})), owner in invalid)

    def test_owner_index_boundaries_and_late_invalid_entry(self):
        # 39 shortest owners fit in Azure's 512-character tag-value limit.
        # Synthetic 100/101-entry inputs additionally exercise the count guard.
        for kind in (RG, VM):
            for count in (1, 2, 39, 100):
                entries = ['a@example.com'] * count
                self.assertFalse(violation('owner', resource(kind, {'owner': ','.join(entries)})))
                for position in (0, count // 2, count - 1):
                    invalid = entries.copy()
                    invalid[position] = 'b@gmail.com'
                    self.assertTrue(violation('owner', resource(kind, {'owner': ','.join(invalid)})))
            self.assertTrue(violation('owner', resource(kind, {'owner': ','.join(['a@example.com'] * 101)})))

    def test_configurable_domain_and_rg_patterns(self):
        parameters = {'ownerDomain': 'sample.org', 'rgNamePatterns': ['X###RG??##']}
        self.assertFalse(violation('owner', resource(RG, {'owner': 'a@sample.org'}, 'X123RGAB01'), **parameters))
        self.assertTrue(violation('owner', resource(RG, {'owner': 'a@example.com'}, 'X123RGAB01'), **parameters))
        self.assertFalse(violation('owner', resource(RG, {}, 'R123RGAB01'), **parameters))
        self.assertTrue(violation('owner', resource(VM, {}, 'X123RGAB01'), **parameters))

    def test_allowed_values_and_project_rules_remain_case_sensitive(self):
        for kind in (RG, VM):
            for tag in ('department', 'environment'):
                param = 'allowed' + tag.title() + 'Values'
                for value in POLICIES[tag]['parameters'][param]['defaultValue']:
                    self.assertFalse(violation(tag, resource(kind, {tag: value})))
                    self.assertTrue(violation(tag, resource(kind, {tag: value.lower()})))
                self.assertFalse(violation(tag, resource(kind, {tag: 'Custom'}), **{param: ['Custom']}))
                self.assertTrue(violation(tag, resource(kind, {tag: 'A-B'}), **{param: ['A.B']}))
            for value in ('A,,B', ',A', 'A,', 'A, B', 'A ,B'):
                self.assertTrue(violation('project', resource(kind, {'project': value})))

    def test_initiative_parameter_mapping_and_effect_contract(self):
        initiative = json.loads((ROOT / 'initiative/rg-tag-governance-initiative.json').read_text())['properties']
        self.assertEqual(len(initiative['policyDefinitions']), 4)
        for reference in initiative['policyDefinitions']:
            policy = POLICIES[reference['policyDefinitionReferenceId'].removeprefix('require-tag-')]
            self.assertEqual(policy['mode'], 'All')
            self.assertEqual(policy['parameters']['effect']['defaultValue'], 'Audit')
            for effect in ('Audit', 'Deny', 'Disabled'):
                evaluator = PolicyEvaluator(policy, resource(VM), {'effect': effect})
                self.assertEqual(evaluator.expression(policy['policyRule']['then']['effect']), effect)
            for name, value in reference['parameters'].items():
                self.assertIn(name, policy['parameters'])
                self.assertIn(name, initiative['parameters'])
                self.assertEqual(value['value'], f"[parameters('{name}')]")


if __name__ == '__main__':
    unittest.main()
