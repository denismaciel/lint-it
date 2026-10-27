from __future__ import annotations

from lint_it.core import Rule
from lint_it.rules.pal001 import NoArgumentDefaultsRule
from lint_it.rules.pal002 import NoTestMocksRule
from lint_it.rules.pal003 import DomainImportRule
from lint_it.rules.pal004 import EnvironmentAccessRule
from lint_it.rules.pal005 import TransactionBoundaryRule
from lint_it.rules.pal006 import RouterConstructionRule
from lint_it.rules.pal007 import NoDomainFastApiRule
from lint_it.rules.pal008 import NoServerImportsRule
from lint_it.rules.pal009 import DomainSqlAlchemyImportRule
from lint_it.rules.pal010 import DomainPersistenceImportRule
from lint_it.rules.pal011 import HiddenNondeterminismRule
from lint_it.rules.pal012 import BoundaryValidationRule
from lint_it.rules.pal013 import ExplicitPolicyTypesRule
from lint_it.rules.pal014 import ImperativeShellRule
from lint_it.rules.pal015 import ExpectedOutcomeRule
from lint_it.rules.pal016 import ClassificationRule
from lint_it.rules.pal017 import LayerDependencyRule
from lint_it.rules.pal018 import RuntimeSettingsRule
from lint_it.rules.pal019 import BorrowedMutationRule
from lint_it.rules.pal020 import AmbientStateRule
from lint_it.rules.pal021 import ImmutableValueRule
from lint_it.rules.pal022 import SynchronousCoreRule
from lint_it.rules.pal023 import EffectfulCapabilityRule
from lint_it.rules.pal024 import ServiceBoundaryDependencyRule

ALL_RULES: tuple[Rule, ...] = (
    NoArgumentDefaultsRule(),
    NoTestMocksRule(),
    DomainImportRule(),
    EnvironmentAccessRule(),
    TransactionBoundaryRule(),
    RouterConstructionRule(),
    NoDomainFastApiRule(),
    NoServerImportsRule(),
    DomainSqlAlchemyImportRule(),
    DomainPersistenceImportRule(),
    HiddenNondeterminismRule(),
    BoundaryValidationRule(),
    ExplicitPolicyTypesRule(),
    ImperativeShellRule(),
    ExpectedOutcomeRule(),
    ClassificationRule(),
    LayerDependencyRule(),
    RuntimeSettingsRule(),
    SynchronousCoreRule(),
    ImmutableValueRule(),
    AmbientStateRule(),
    BorrowedMutationRule(),
    EffectfulCapabilityRule(),
    ServiceBoundaryDependencyRule(),
)

RULES_BY_CODE = {rule.code: rule for rule in ALL_RULES}
