"""Adds config flow for Workday integration."""

from __future__ import annotations

from functools import partial
import json
from typing import Any

from holidays import PUBLIC, HolidayBase, country_holidays, list_supported_countries
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_COUNTRY, CONF_LANGUAGE, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    CountrySelector,
    CountrySelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    LanguageSelector,
    LanguageSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util

from .const import (
    ALLOWED_DAYS,
    CONF_ADD_HOLIDAYS,
    CONF_CATEGORY,
    CONF_EXCLUDES,
    CONF_EXCLUSION_CALENDARS,
    CONF_EXCLUSION_CALENDAR_RULES,
    CONF_OFFSET,
    CONF_REFRESH_INTERVAL_MINUTES,
    CONF_PROVINCE,
    CONF_REMOVE_HOLIDAYS,
    CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
    CONF_TRIGGER_ON_EVENT_WORDS,
    CONF_WORKDAYS,
    DEFAULT_EXCLUDES,
    DEFAULT_EXCLUSION_CALENDAR_RULES,
    DEFAULT_NAME,
    DEFAULT_OFFSET,
    DEFAULT_REFRESH_INTERVAL_MINUTES,
    DEFAULT_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
    DEFAULT_TRIGGER_ON_EVENT_WORDS,
    DEFAULT_WORKDAYS,
    DOMAIN,
    LOGGER,
)


def add_province_and_language_to_schema(
    schema: vol.Schema,
    country: str | None,
) -> vol.Schema:
    """Update schema with province from country."""
    if not country:
        return schema

    all_countries = list_supported_countries(include_aliases=False)

    language_schema = {}
    province_schema = {}

    _country = country_holidays(country=country)
    if country_default_language := (_country.default_language):
        new_selectable_languages = list(_country.supported_languages)
        language_schema = {
            vol.Optional(
                CONF_LANGUAGE, default=country_default_language
            ): LanguageSelector(
                LanguageSelectorConfig(
                    languages=new_selectable_languages, native_name=True
                )
            )
        }

    if provinces := all_countries.get(country):
        if _country.subdivisions_aliases and (
            subdiv_aliases := _country.get_subdivision_aliases()
        ):
            province_options: list[Any] = [
                SelectOptionDict(value=k, label=", ".join(v))
                for k, v in subdiv_aliases.items()
            ]
            for option in province_options:
                if option["label"] == "":
                    option["label"] = option["value"]
        else:
            province_options = provinces
        province_schema = {
            vol.Optional(CONF_PROVINCE): SelectSelector(
                SelectSelectorConfig(
                    options=province_options,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_PROVINCE,
                )
            ),
        }

    category_schema = {}
    # PUBLIC will always be included and can therefore not be set/removed
    _categories = [x for x in _country.supported_categories if x != PUBLIC]
    if _categories:
        category_schema = {
            vol.Optional(CONF_CATEGORY): SelectSelector(
                SelectSelectorConfig(
                    options=_categories,
                    mode=SelectSelectorMode.DROPDOWN,
                    multiple=True,
                    translation_key=CONF_CATEGORY,
                )
            ),
        }

    return vol.Schema(
        {
            **DATA_SCHEMA_OPT.schema,
            **language_schema,
            **province_schema,
            **category_schema,
        }
    )


def _is_valid_date_range(check_date: str, error: type[HomeAssistantError]) -> bool:
    """Validate date range."""
    if check_date.find(",") > 0:
        dates = check_date.split(",", maxsplit=1)
        for date in dates:
            if dt_util.parse_date(date) is None:
                raise error("Incorrect date in range")
        return True
    return False


def validate_custom_dates(user_input: dict[str, Any]) -> None:
    """Validate custom dates for add/remove holidays."""
    for add_date in user_input[CONF_ADD_HOLIDAYS]:
        if (
            not _is_valid_date_range(add_date, AddDateRangeError)
            and dt_util.parse_date(add_date) is None
        ):
            raise AddDatesError("Incorrect date")

    year: int = dt_util.now().year
    if country := user_input.get(CONF_COUNTRY):
        language: str | None = user_input.get(CONF_LANGUAGE)
        province = user_input.get(CONF_PROVINCE)
        obj_holidays = country_holidays(
            country=country,
            subdiv=province,
            years=year,
            language=language,
            categories=[PUBLIC, *user_input.get(CONF_CATEGORY, [])],
        )

    else:
        obj_holidays = HolidayBase(years=year)

    for remove_date in user_input[CONF_REMOVE_HOLIDAYS]:
        if (
            not _is_valid_date_range(remove_date, RemoveDateRangeError)
            and dt_util.parse_date(remove_date) is None
            and obj_holidays.get_named(remove_date) == []
        ):
            raise RemoveDatesError("Incorrect date or name")


def normalize_exclusion_calendar_rules(
    raw_rules: Any,
    exclusion_calendars: list[str],
) -> dict[str, dict[str, Any]]:
    """Validate and normalize per-calendar exclusion rules."""
    if raw_rules in (None, "", {}):
        parsed_rules: Any = {}
    elif isinstance(raw_rules, str):
        try:
            parsed_rules = json.loads(raw_rules)
        except json.JSONDecodeError as err:
            raise CalendarRulesError("Invalid JSON") from err
    elif isinstance(raw_rules, dict):
        parsed_rules = raw_rules
    else:
        raise CalendarRulesError("Rules must be JSON object")

    if not isinstance(parsed_rules, dict):
        raise CalendarRulesError("Rules must be JSON object")

    normalized_rules: dict[str, dict[str, Any]] = {}
    selected_calendar_ids = set(exclusion_calendars)
    for calendar_entity_id, calendar_rule in parsed_rules.items():
        if not isinstance(calendar_entity_id, str) or not calendar_entity_id:
            raise CalendarRulesError("Calendar key must be non-empty string")
        if selected_calendar_ids and calendar_entity_id not in selected_calendar_ids:
            raise CalendarRulesError("Calendar key must exist in exclusion calendars")
        if not isinstance(calendar_rule, dict):
            raise CalendarRulesError("Calendar rule must be object")

        trigger_on_all_day = calendar_rule.get(
            CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
            DEFAULT_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
        )
        if not isinstance(trigger_on_all_day, bool):
            raise CalendarRulesError(
                f"{CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS} must be true/false"
            )

        trigger_words = calendar_rule.get(
            CONF_TRIGGER_ON_EVENT_WORDS,
            DEFAULT_TRIGGER_ON_EVENT_WORDS,
        )
        if not isinstance(trigger_words, list) or any(
            not isinstance(word, str) for word in trigger_words
        ):
            raise CalendarRulesError(f"{CONF_TRIGGER_ON_EVENT_WORDS} must be string list")

        normalized_rules[calendar_entity_id] = {
            CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS: trigger_on_all_day,
            CONF_TRIGGER_ON_EVENT_WORDS: [word.strip() for word in trigger_words if word.strip()],
        }

    return normalized_rules


def serialize_exclusion_calendar_rules(rules: Any) -> str:
    """Serialize per-calendar exclusion rules for form display."""
    if isinstance(rules, str):
        return rules
    if isinstance(rules, dict):
        return json.dumps(rules, indent=2)
    return "{}"


def form_values_with_serialized_calendar_rules(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert rules object into display string for selector forms."""
    if values is None:
        return None

    formatted_values = dict(values)
    formatted_values[CONF_EXCLUSION_CALENDAR_RULES] = serialize_exclusion_calendar_rules(
        formatted_values.get(CONF_EXCLUSION_CALENDAR_RULES, DEFAULT_EXCLUSION_CALENDAR_RULES)
    )
    return formatted_values


DATA_SCHEMA_OPT = vol.Schema(
    {
        vol.Optional(CONF_WORKDAYS, default=DEFAULT_WORKDAYS): SelectSelector(
            SelectSelectorConfig(
                options=ALLOWED_DAYS,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="days",
            )
        ),
        vol.Optional(CONF_EXCLUDES, default=DEFAULT_EXCLUDES): SelectSelector(
            SelectSelectorConfig(
                options=ALLOWED_DAYS,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="days",
            )
        ),
        vol.Optional(CONF_OFFSET, default=DEFAULT_OFFSET): NumberSelector(
            NumberSelectorConfig(min=-10, max=10, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(
            CONF_REFRESH_INTERVAL_MINUTES,
            default=DEFAULT_REFRESH_INTERVAL_MINUTES,
        ): NumberSelector(
            NumberSelectorConfig(min=1, max=180, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_EXCLUSION_CALENDARS, default=[]): EntitySelector(
            EntitySelectorConfig(domain=["calendar"], multiple=True)
        ),
        vol.Optional(
            CONF_EXCLUSION_CALENDAR_RULES,
            default="{}",
        ): TextSelector(),
        vol.Optional(CONF_ADD_HOLIDAYS, default=[]): SelectSelector(
            SelectSelectorConfig(
                options=[],
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_REMOVE_HOLIDAYS, default=[]): SelectSelector(
            SelectSelectorConfig(
                options=[],
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class WorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Workday integration."""

    VERSION = 1

    data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> WorkdayOptionsFlowHandler:
        """Get the options flow for this handler."""
        return WorkdayOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user initial step."""
        errors: dict[str, str] = {}

        supported_countries = await self.hass.async_add_executor_job(
            partial(list_supported_countries, include_aliases=False)
        )

        if user_input is not None:
            self.data = user_input
            return await self.async_step_options()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
                    vol.Optional(CONF_COUNTRY): CountrySelector(
                        CountrySelectorConfig(
                            countries=list(supported_countries),
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle remaining flow."""
        errors: dict[str, str] = {}
        if user_input is not None:
            combined_input: dict[str, Any] = {**self.data, **user_input}
            combined_input.setdefault(CONF_EXCLUSION_CALENDARS, [])
            combined_input.setdefault(CONF_EXCLUSION_CALENDAR_RULES, "{}")
            combined_input.setdefault(
                CONF_REFRESH_INTERVAL_MINUTES,
                DEFAULT_REFRESH_INTERVAL_MINUTES,
            )

            try:
                combined_input[CONF_EXCLUSION_CALENDAR_RULES] = (
                    normalize_exclusion_calendar_rules(
                        combined_input.get(CONF_EXCLUSION_CALENDAR_RULES),
                        combined_input[CONF_EXCLUSION_CALENDARS],
                    )
                )
            except CalendarRulesError:
                errors[CONF_EXCLUSION_CALENDAR_RULES] = "invalid_calendar_rules"

            try:
                await self.hass.async_add_executor_job(
                    validate_custom_dates, combined_input
                )
            except AddDatesError:
                errors["add_holidays"] = "add_holiday_error"
            except AddDateRangeError:
                errors["add_holidays"] = "add_holiday_range_error"
            except RemoveDatesError:
                errors["remove_holidays"] = "remove_holiday_error"
            except RemoveDateRangeError:
                errors["remove_holidays"] = "remove_holiday_range_error"

            abort_match = {
                CONF_COUNTRY: combined_input.get(CONF_COUNTRY),
                CONF_EXCLUDES: combined_input[CONF_EXCLUDES],
                CONF_OFFSET: combined_input[CONF_OFFSET],
                CONF_REFRESH_INTERVAL_MINUTES: combined_input[
                    CONF_REFRESH_INTERVAL_MINUTES
                ],
                CONF_WORKDAYS: combined_input[CONF_WORKDAYS],
                CONF_EXCLUSION_CALENDARS: combined_input[CONF_EXCLUSION_CALENDARS],
                CONF_EXCLUSION_CALENDAR_RULES: combined_input[
                    CONF_EXCLUSION_CALENDAR_RULES
                ],
                CONF_ADD_HOLIDAYS: combined_input[CONF_ADD_HOLIDAYS],
                CONF_REMOVE_HOLIDAYS: combined_input[CONF_REMOVE_HOLIDAYS],
                CONF_PROVINCE: combined_input.get(CONF_PROVINCE),
            }
            if CONF_CATEGORY in combined_input:
                abort_match[CONF_CATEGORY] = combined_input[CONF_CATEGORY]
            LOGGER.debug("abort_check in options with %s", combined_input)
            self._async_abort_entries_match(abort_match)

            LOGGER.debug("Errors have occurred %s", errors)
            if not errors:
                LOGGER.debug("No duplicate, no errors, creating entry")
                return self.async_create_entry(
                    title=combined_input[CONF_NAME],
                    data={},
                    options=combined_input,
                )

        schema = await self.hass.async_add_executor_job(
            add_province_and_language_to_schema,
            DATA_SCHEMA_OPT,
            self.data.get(CONF_COUNTRY),
        )
        new_schema = self.add_suggested_values_to_schema(
            schema,
            form_values_with_serialized_calendar_rules(user_input),
        )
        return self.async_show_form(
            step_id="options",
            data_schema=new_schema,
            errors=errors,
            description_placeholders={
                "name": self.data[CONF_NAME],
                "country": self.data.get(CONF_COUNTRY, "-"),
            },
        )


class WorkdayOptionsFlowHandler(OptionsFlowWithReload):
    """Handle Workday options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Workday options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            combined_input: dict[str, Any] = {**self.config_entry.options, **user_input}
            combined_input.setdefault(CONF_EXCLUSION_CALENDARS, [])
            combined_input.setdefault(CONF_EXCLUSION_CALENDAR_RULES, "{}")
            combined_input.setdefault(
                CONF_REFRESH_INTERVAL_MINUTES,
                DEFAULT_REFRESH_INTERVAL_MINUTES,
            )

            try:
                combined_input[CONF_EXCLUSION_CALENDAR_RULES] = (
                    normalize_exclusion_calendar_rules(
                        combined_input.get(CONF_EXCLUSION_CALENDAR_RULES),
                        combined_input[CONF_EXCLUSION_CALENDARS],
                    )
                )
            except CalendarRulesError:
                errors[CONF_EXCLUSION_CALENDAR_RULES] = "invalid_calendar_rules"

            if CONF_PROVINCE not in user_input:
                # Province not present, delete old value (if present) too
                combined_input.pop(CONF_PROVINCE, None)

            try:
                await self.hass.async_add_executor_job(
                    validate_custom_dates, combined_input
                )
            except AddDatesError:
                errors["add_holidays"] = "add_holiday_error"
            except AddDateRangeError:
                errors["add_holidays"] = "add_holiday_range_error"
            except RemoveDatesError:
                errors["remove_holidays"] = "remove_holiday_error"
            except RemoveDateRangeError:
                errors["remove_holidays"] = "remove_holiday_range_error"
            else:
                LOGGER.debug("abort_check in options with %s", combined_input)
                abort_match = {
                    CONF_COUNTRY: self.config_entry.options.get(CONF_COUNTRY),
                    CONF_EXCLUDES: combined_input[CONF_EXCLUDES],
                    CONF_OFFSET: combined_input[CONF_OFFSET],
                    CONF_REFRESH_INTERVAL_MINUTES: combined_input[
                        CONF_REFRESH_INTERVAL_MINUTES
                    ],
                    CONF_WORKDAYS: combined_input[CONF_WORKDAYS],
                    CONF_EXCLUSION_CALENDARS: combined_input[
                        CONF_EXCLUSION_CALENDARS
                    ],
                    CONF_EXCLUSION_CALENDAR_RULES: combined_input[
                        CONF_EXCLUSION_CALENDAR_RULES
                    ],
                    CONF_ADD_HOLIDAYS: combined_input[CONF_ADD_HOLIDAYS],
                    CONF_REMOVE_HOLIDAYS: combined_input[CONF_REMOVE_HOLIDAYS],
                    CONF_PROVINCE: combined_input.get(CONF_PROVINCE),
                }
                if CONF_CATEGORY in combined_input:
                    abort_match[CONF_CATEGORY] = combined_input[CONF_CATEGORY]
                try:
                    self._async_abort_entries_match(abort_match)
                except AbortFlow as err:
                    errors = {"base": err.reason}
                else:
                    return self.async_create_entry(data=combined_input)

        options = self.config_entry.options
        schema: vol.Schema = await self.hass.async_add_executor_job(
            add_province_and_language_to_schema,
            DATA_SCHEMA_OPT,
            options.get(CONF_COUNTRY),
        )

        new_schema = self.add_suggested_values_to_schema(
            schema,
            form_values_with_serialized_calendar_rules(user_input or options),
        )
        LOGGER.debug("Errors have occurred in options %s", errors)
        return self.async_show_form(
            step_id="init",
            data_schema=new_schema,
            errors=errors,
            description_placeholders={
                "name": options[CONF_NAME],
                "country": options.get(CONF_COUNTRY, "-"),
            },
        )


class AddDatesError(HomeAssistantError):
    """Exception for error adding dates."""


class AddDateRangeError(HomeAssistantError):
    """Exception for error adding dates."""


class RemoveDatesError(HomeAssistantError):
    """Exception for error removing dates."""


class RemoveDateRangeError(HomeAssistantError):
    """Exception for error removing dates."""


class CalendarRulesError(HomeAssistantError):
    """Exception for invalid exclusion calendar rules."""


class CountryNotExist(HomeAssistantError):
    """Exception country does not exist error."""
