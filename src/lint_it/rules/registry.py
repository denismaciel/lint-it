from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from lint_it.core import Rule
from lint_it.rules.ambient_state import AmbientStateRule
from lint_it.rules.async_core import AsyncCoreRule
from lint_it.rules.borrowed_mutation import BorrowedMutationRule
from lint_it.rules.capabilities import EffectfulCapabilityRule
from lint_it.rules.client_imports import ClientImportRule
from lint_it.rules.defaults import ImmutableDefaultRule
from lint_it.rules.environment import EnvironmentAccessRule
from lint_it.rules.forbidden_imports import ForbiddenImportRule
from lint_it.rules.frozen_values import FrozenValueRule
from lint_it.rules.io_calls import IoCallRule
from lint_it.rules.layer_dependencies import LayerDependencyRule
from lint_it.rules.meta import ManifestRule, ParseErrorRule, UnclassifiedFileRule
from lint_it.rules.mocking import MockingRule
from lint_it.rules.nondeterminism import NondeterminismRule
from lint_it.rules.outcomes import ExpectedOutcomeRule
from lint_it.rules.policy_types import BooleanPolicyRule
from lint_it.rules.routers import RouterConstructionRule
from lint_it.rules.subclassing import SubclassingRule
from lint_it.rules.transactions import TransactionBoundaryRule

PARSE_ERROR = ParseErrorRule()
MANIFEST = ManifestRule()

ALL_RULES: tuple[Rule, ...] = (
    PARSE_ERROR,
    UnclassifiedFileRule(),
    MANIFEST,
    LayerDependencyRule(),
    ForbiddenImportRule(),
    ClientImportRule(),
    NondeterminismRule(),
    IoCallRule(),
    AmbientStateRule(),
    BorrowedMutationRule(),
    FrozenValueRule(),
    AsyncCoreRule(),
    EffectfulCapabilityRule(),
    EnvironmentAccessRule(),
    TransactionBoundaryRule(),
    RouterConstructionRule(),
    MockingRule(),
    ImmutableDefaultRule(),
    BooleanPolicyRule(),
    ExpectedOutcomeRule(),
    SubclassingRule(),
)

RULES_BY_CODE: Mapping[str, Rule] = MappingProxyType({rule.code: rule for rule in ALL_RULES})
