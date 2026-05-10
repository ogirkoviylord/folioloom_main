from __future__ import annotations

from typing import Protocol

from translator_service.admin.settings import (
    AdminSettingDefinition,
    SettingApplyMode,
    SettingValueType,
)
from translator_service.beta_safety import BetaSafetyLimits, BetaSafetyRates


class BetaSafetyDefaults(Protocol):
    beta_translations_paused: bool
    beta_global_daily_cost_cap_usd: float
    beta_global_monthly_cost_cap_usd: float
    beta_user_daily_cost_cap_usd: float
    beta_user_monthly_cost_cap_usd: float
    beta_user_daily_job_limit: int
    beta_max_job_estimated_cost_usd: float
    beta_cost_input_usd_per_million: float
    beta_cost_output_usd_per_million: float
    beta_cost_warning_fraction: float


def _definition(
    *,
    key: str,
    label: str,
    value_type: SettingValueType,
    default_value: str,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> AdminSettingDefinition:
    return AdminSettingDefinition(
        key=key,
        label=label,
        value_type=value_type,
        apply_mode=SettingApplyMode.LIVE,
        default_value=default_value,
        minimum=minimum,
        maximum=maximum,
    )


BETA_TRANSLATIONS_PAUSED_SETTING = _definition(
    key="BETA_TRANSLATIONS_PAUSED",
    label="Pause all beta translations",
    value_type=SettingValueType.BOOLEAN,
    default_value="false",
)
BETA_GLOBAL_DAILY_COST_CAP_USD_SETTING = _definition(
    key="BETA_GLOBAL_DAILY_COST_CAP_USD",
    label="Global daily cost cap USD",
    value_type=SettingValueType.FLOAT,
    default_value="5.00",
    minimum=0.0,
)
BETA_GLOBAL_MONTHLY_COST_CAP_USD_SETTING = _definition(
    key="BETA_GLOBAL_MONTHLY_COST_CAP_USD",
    label="Global monthly cost cap USD",
    value_type=SettingValueType.FLOAT,
    default_value="50.00",
    minimum=0.0,
)
BETA_USER_DAILY_COST_CAP_USD_SETTING = _definition(
    key="BETA_USER_DAILY_COST_CAP_USD",
    label="Per-user daily cost cap USD",
    value_type=SettingValueType.FLOAT,
    default_value="1.00",
    minimum=0.0,
)
BETA_USER_MONTHLY_COST_CAP_USD_SETTING = _definition(
    key="BETA_USER_MONTHLY_COST_CAP_USD",
    label="Per-user monthly cost cap USD",
    value_type=SettingValueType.FLOAT,
    default_value="10.00",
    minimum=0.0,
)
BETA_USER_DAILY_JOB_LIMIT_SETTING = _definition(
    key="BETA_USER_DAILY_JOB_LIMIT",
    label="Per-user daily job limit",
    value_type=SettingValueType.INTEGER,
    default_value="3",
    minimum=0,
)
BETA_MAX_JOB_ESTIMATED_COST_USD_SETTING = _definition(
    key="BETA_MAX_JOB_ESTIMATED_COST_USD",
    label="Max estimated cost per job USD",
    value_type=SettingValueType.FLOAT,
    default_value="2.00",
    minimum=0.0,
)
BETA_COST_WARNING_FRACTION_SETTING = _definition(
    key="BETA_COST_WARNING_FRACTION",
    label="Budget warning fraction",
    value_type=SettingValueType.FLOAT,
    default_value="0.80",
    minimum=0.0,
    maximum=1.0,
)

BETA_SAFETY_SETTING_DEFINITIONS = (
    BETA_TRANSLATIONS_PAUSED_SETTING,
    BETA_GLOBAL_DAILY_COST_CAP_USD_SETTING,
    BETA_GLOBAL_MONTHLY_COST_CAP_USD_SETTING,
    BETA_USER_DAILY_COST_CAP_USD_SETTING,
    BETA_USER_MONTHLY_COST_CAP_USD_SETTING,
    BETA_USER_DAILY_JOB_LIMIT_SETTING,
    BETA_MAX_JOB_ESTIMATED_COST_USD_SETTING,
    BETA_COST_WARNING_FRACTION_SETTING,
)


def beta_safety_setting_definitions_from_settings(
    defaults: BetaSafetyDefaults,
) -> tuple[AdminSettingDefinition, ...]:
    values = {
        "BETA_TRANSLATIONS_PAUSED": str(defaults.beta_translations_paused).lower(),
        "BETA_GLOBAL_DAILY_COST_CAP_USD": str(defaults.beta_global_daily_cost_cap_usd),
        "BETA_GLOBAL_MONTHLY_COST_CAP_USD": str(
            defaults.beta_global_monthly_cost_cap_usd
        ),
        "BETA_USER_DAILY_COST_CAP_USD": str(defaults.beta_user_daily_cost_cap_usd),
        "BETA_USER_MONTHLY_COST_CAP_USD": str(defaults.beta_user_monthly_cost_cap_usd),
        "BETA_USER_DAILY_JOB_LIMIT": str(defaults.beta_user_daily_job_limit),
        "BETA_MAX_JOB_ESTIMATED_COST_USD": str(
            defaults.beta_max_job_estimated_cost_usd
        ),
        "BETA_COST_WARNING_FRACTION": str(defaults.beta_cost_warning_fraction),
    }
    return tuple(
        AdminSettingDefinition(
            key=definition.key,
            label=definition.label,
            value_type=definition.value_type,
            apply_mode=definition.apply_mode,
            default_value=values[definition.key],
            minimum=definition.minimum,
            maximum=definition.maximum,
            sensitive=definition.sensitive,
            allow_empty=definition.allow_empty,
        )
        for definition in BETA_SAFETY_SETTING_DEFINITIONS
    )


def load_beta_safety_limits(
    settings_store,
    defaults: BetaSafetyDefaults,
) -> BetaSafetyLimits:
    definitions = {
        definition.key: definition
        for definition in beta_safety_setting_definitions_from_settings(defaults)
    }

    return BetaSafetyLimits(
        translations_paused=_setting_bool(
            settings_store,
            definitions["BETA_TRANSLATIONS_PAUSED"],
        ),
        global_daily_cost_cap_usd=_setting_float(
            settings_store,
            definitions["BETA_GLOBAL_DAILY_COST_CAP_USD"],
        ),
        global_monthly_cost_cap_usd=_setting_float(
            settings_store,
            definitions["BETA_GLOBAL_MONTHLY_COST_CAP_USD"],
        ),
        user_daily_cost_cap_usd=_setting_float(
            settings_store,
            definitions["BETA_USER_DAILY_COST_CAP_USD"],
        ),
        user_monthly_cost_cap_usd=_setting_float(
            settings_store,
            definitions["BETA_USER_MONTHLY_COST_CAP_USD"],
        ),
        user_daily_job_limit=_setting_int(
            settings_store,
            definitions["BETA_USER_DAILY_JOB_LIMIT"],
        ),
        max_job_estimated_cost_usd=_setting_float(
            settings_store,
            definitions["BETA_MAX_JOB_ESTIMATED_COST_USD"],
        ),
        warning_fraction=_clamp(
            _setting_float(settings_store, definitions["BETA_COST_WARNING_FRACTION"]),
            minimum=0.0,
            maximum=1.0,
        ),
    )


def beta_safety_rates_from_settings(defaults: BetaSafetyDefaults) -> BetaSafetyRates:
    return BetaSafetyRates(
        input_usd_per_million=defaults.beta_cost_input_usd_per_million,
        output_usd_per_million=defaults.beta_cost_output_usd_per_million,
    )


def _setting_bool(settings_store, definition: AdminSettingDefinition) -> bool:
    return settings_store.get_value(definition).value.strip().lower() == "true"


def _setting_float(settings_store, definition: AdminSettingDefinition) -> float:
    return float(settings_store.get_value(definition).value)


def _setting_int(settings_store, definition: AdminSettingDefinition) -> int:
    return int(settings_store.get_value(definition).value)


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
