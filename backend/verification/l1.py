from __future__ import annotations
from models.events import CheckResult, VerificationSnapshot


def make_check(
    name: str,
    passed: bool,
    detail: str,
    severity: str = "warn",
) -> CheckResult:
    return CheckResult(
        name=name,
        passed=passed,
        severity="info" if passed else severity,
        detail=detail,
    )


def make_verification(checks: list[CheckResult]) -> VerificationSnapshot:
    pass_rate = sum(1 for c in checks if c.passed) / len(checks) if checks else 0.0
    return VerificationSnapshot(l1_checks=checks, l1_pass_rate=pass_rate)
