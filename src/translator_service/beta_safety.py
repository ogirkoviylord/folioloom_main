from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

BETA_SAFETY_ALLOWED = "allowed"
BETA_SAFETY_KILL_SWITCH = "kill_switch"
BETA_SAFETY_GLOBAL_DAILY_CAP = "global_daily_cap"
BETA_SAFETY_GLOBAL_MONTHLY_CAP = "global_monthly_cap"
BETA_SAFETY_USER_DAILY_CAP = "user_daily_cap"
BETA_SAFETY_USER_MONTHLY_CAP = "user_monthly_cap"
BETA_SAFETY_USER_DAILY_JOB_LIMIT = "user_daily_job_limit"
BETA_SAFETY_JOB_ESTIMATE_CAP = "job_estimate_cap"
BETA_SAFETY_RESERVATION_EXISTS = "reservation_exists"


_SAFE_MESSAGES = {
    BETA_SAFETY_ALLOWED: "The translation can start.",
    BETA_SAFETY_KILL_SWITCH: "Translations are temporarily paused.",
    BETA_SAFETY_JOB_ESTIMATE_CAP: (
        "This translation cannot start under the current beta limits."
    ),
    BETA_SAFETY_USER_DAILY_JOB_LIMIT: (
        "You have reached today's beta translation limit."
    ),
    BETA_SAFETY_GLOBAL_DAILY_CAP: "Translations are temporarily limited for today.",
    BETA_SAFETY_GLOBAL_MONTHLY_CAP: "Translations are temporarily limited this month.",
    BETA_SAFETY_USER_DAILY_CAP: "You have reached today's beta translation limit.",
    BETA_SAFETY_USER_MONTHLY_CAP: (
        "You have reached this month's beta translation limit."
    ),
    BETA_SAFETY_RESERVATION_EXISTS: "This translation is already reserved.",
}


@dataclass(frozen=True)
class BetaSafetyRates:
    input_usd_per_million: float = 0.28
    output_usd_per_million: float = 1.10


@dataclass(frozen=True)
class BetaSafetyLimits:
    translations_paused: bool = False
    global_daily_cost_cap_usd: float | None = 5.0
    global_monthly_cost_cap_usd: float | None = 50.0
    user_daily_cost_cap_usd: float | None = 1.0
    user_monthly_cost_cap_usd: float | None = 10.0
    user_daily_job_limit: int = 3
    max_job_estimated_cost_usd: float | None = 2.0
    warning_fraction: float = 0.8


@dataclass(frozen=True)
class JobCostEstimate:
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class BudgetSnapshot:
    global_daily_reserved_usd: float = 0.0
    global_daily_consumed_usd: float = 0.0
    global_monthly_reserved_usd: float = 0.0
    global_monthly_consumed_usd: float = 0.0
    user_daily_reserved_usd: float = 0.0
    user_daily_consumed_usd: float = 0.0
    user_monthly_reserved_usd: float = 0.0
    user_monthly_consumed_usd: float = 0.0
    user_daily_active_jobs: int = 0


@dataclass(frozen=True)
class BetaSafetyDecision:
    allowed: bool
    reason_code: str
    safe_message: str


class BetaSafetyGuard(Protocol):
    def can_start_new_work(self) -> BetaSafetyDecision:
        ...

    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        ...

    def release_job(self, *, job_id: str, reason: str) -> None:
        ...

    def mark_job_consumed(self, *, job_id: str) -> None:
        ...

    def record_work_unit_usage(
        self,
        *,
        job_id: str,
        user_id: str,
        work_unit_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        ...


def estimate_cost_usd(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    rates: BetaSafetyRates,
) -> float:
    prompt_cost = (max(0, prompt_tokens) / 1_000_000.0) * rates.input_usd_per_million
    completion_cost = (
        max(0, completion_tokens) / 1_000_000.0
    ) * rates.output_usd_per_million
    return round(prompt_cost + completion_cost, 6)


def decide_beta_safety(
    *,
    estimate: JobCostEstimate,
    limits: BetaSafetyLimits,
    budget: BudgetSnapshot,
) -> BetaSafetyDecision:
    estimated_cost = max(0.0, estimate.estimated_cost_usd)

    if limits.translations_paused:
        return _blocked(BETA_SAFETY_KILL_SWITCH)
    if _would_exceed(estimated_cost, 0.0, limits.max_job_estimated_cost_usd):
        return _blocked(BETA_SAFETY_JOB_ESTIMATE_CAP)
    if budget.user_daily_active_jobs >= limits.user_daily_job_limit:
        return _blocked(BETA_SAFETY_USER_DAILY_JOB_LIMIT)
    if _would_exceed(
        estimated_cost,
        budget.global_daily_reserved_usd + budget.global_daily_consumed_usd,
        limits.global_daily_cost_cap_usd,
    ):
        return _blocked(BETA_SAFETY_GLOBAL_DAILY_CAP)
    if _would_exceed(
        estimated_cost,
        budget.global_monthly_reserved_usd + budget.global_monthly_consumed_usd,
        limits.global_monthly_cost_cap_usd,
    ):
        return _blocked(BETA_SAFETY_GLOBAL_MONTHLY_CAP)
    if _would_exceed(
        estimated_cost,
        budget.user_daily_reserved_usd + budget.user_daily_consumed_usd,
        limits.user_daily_cost_cap_usd,
    ):
        return _blocked(BETA_SAFETY_USER_DAILY_CAP)
    if _would_exceed(
        estimated_cost,
        budget.user_monthly_reserved_usd + budget.user_monthly_consumed_usd,
        limits.user_monthly_cost_cap_usd,
    ):
        return _blocked(BETA_SAFETY_USER_MONTHLY_CAP)

    return BetaSafetyDecision(
        allowed=True,
        reason_code=BETA_SAFETY_ALLOWED,
        safe_message=_SAFE_MESSAGES[BETA_SAFETY_ALLOWED],
    )


def _would_exceed(estimate: float, current_total: float, cap: float | None) -> bool:
    if cap is None:
        return False
    return Decimal(str(current_total)) + Decimal(str(estimate)) > Decimal(str(cap))


def _blocked(reason_code: str) -> BetaSafetyDecision:
    return BetaSafetyDecision(
        allowed=False,
        reason_code=reason_code,
        safe_message=_SAFE_MESSAGES[reason_code],
    )
