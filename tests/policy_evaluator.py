"""Small offline evaluator for the policy subset used here, not an Azure emulator.

Evaluates the actual JSON to catch scope/logic regressions. Azure remains the
authority for alias resolution, template function behavior and applicability.
Unsupported syntax fails loudly. Logical branches are all evaluated to expose
unsafe expressions that would otherwise be hidden by short-circuit evaluation.
"""

import ast
import re


def validate_count_sources(value):
    """Catch the Azure authoring restriction reported by InvalidCountExpression.

    This is a targeted regression guard, not a complete Azure policy validator.
    """
    if isinstance(value, dict):
        source = value.get('count', {}).get('value')
        if isinstance(source, str) and re.search(r'\bfield\s*\(', source, re.IGNORECASE):
            raise ValueError('count.value must not contain field()')
        for child in value.values():
            validate_count_sources(child)
    elif isinstance(value, list):
        for child in value:
            validate_count_sources(child)


class PolicyEvaluator:
    def __init__(self, properties, resource, parameters=None):
        validate_count_sources(properties['policyRule'])
        self.resource = resource
        self.parameters = {
            name: value['defaultValue']
            for name, value in properties['parameters'].items()
        }
        self.parameters.update(parameters or {})
        self.current = {}

    def field(self, name):
        tag = re.fullmatch(r"tags\['?([^'\]]+)'?\]", name)
        if tag:
            return next((v for k, v in self.resource.get('tags', {}).items()
                         if k.lower() == tag[1].lower()), None)
        return self.resource.get(name)

    def expression(self, value):
        if not isinstance(value, str) or not value.startswith('['):
            return value
        tree = ast.parse(value[1:-1].replace('if(', 'choose('), mode='eval')
        return self.node(tree.body)

    def node(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Attribute):
            return self.node(node.value)[node.attr]
        if isinstance(node, ast.Subscript):
            return self.node(node.value)[self.node(node.slice)]
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            raise ValueError(ast.dump(node))
        name = node.func.id
        if name == 'choose':
            return self.node(node.args[1] if self.node(node.args[0]) else node.args[2])
        args = [self.node(arg) for arg in node.args]
        functions = {
            'field': self.field,
            'parameters': self.parameters.__getitem__,
            'current': self.current.__getitem__,
            'resourceGroup': lambda: {'name': self.resource['resourceGroup']},
            'equals': lambda a, b: self.fold(a) == self.fold(b),
            'less': lambda a, b: a < b,
            'split': lambda a, b: a.split(b),
            'length': len,
            'first': lambda a: a[0],
            'last': lambda a: a[-1],
            'take': lambda a, n: a[:n],
            'coalesce': lambda *items: next(x for x in items if x is not None),
            'string': lambda a: '' if a is None else str(a),
        }
        return functions[name](*args)

    @staticmethod
    def fold(value):
        return value.casefold() if isinstance(value, str) else value

    def condition(self, rule):
        if 'allOf' in rule:
            return all([self.condition(item) for item in rule['allOf']])
        if 'anyOf' in rule:
            return any([self.condition(item) for item in rule['anyOf']])
        if 'not' in rule:
            return not self.condition(rule['not'])
        if 'count' in rule:
            count = rule['count']
            items = self.expression(count['value'])
            if len(items) > 100:
                raise ValueError('Azure value count iteration limit exceeded')
            left = 0
            for item in items:
                self.current[count['name']] = item
                left += self.condition(count['where'])
            self.current.pop(count['name'], None)
            operand = 'count'
        else:
            operand = 'field' if 'field' in rule else 'value'
            left = self.field(rule[operand]) if operand == 'field' else self.expression(rule[operand])
        operator, right = next((k, self.expression(v)) for k, v in rule.items() if k != operand)
        if operator == 'exists':
            return (left is not None) == (right == 'true')
        left = '' if left is None else left
        a, b = self.fold(left), self.fold(right)
        if operator in ('equals', 'notEquals'):
            return (a == b) == (operator == 'equals')
        if operator in ('in', 'notIn'):
            return (a in [self.fold(x) for x in right]) == (operator == 'in')
        if operator in ('contains', 'notContains'):
            return (b in a) == (operator == 'contains')
        if operator == 'greater':
            return left > right
        if operator == 'match':
            pattern = ''.join({'#': '[0-9]', '?': '[a-zA-Z]', '.': '.'}.get(c, re.escape(c)) for c in right)
            return re.fullmatch(pattern, left) is not None
        if operator == 'like':
            return re.fullmatch(re.escape(b).replace(r'\*', '.*'), a, re.DOTALL) is not None
        raise ValueError(operator)
