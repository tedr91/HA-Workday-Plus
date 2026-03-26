# Workday Plus

`Workday Plus` is a Home Assistant custom integration for HACS, based on the built-in `workday` integration.

It provides:
- A binary sensor entity to indicate whether a date is a workday
- A calendar entity with workday events
- A `workday_plus.check_date` service
- Config flow + options flow (country, province, language, includes/excludes, offsets, add/remove holidays)

## Installation (HACS)

1. Open **HACS** in Home Assistant.
2. Go to **Integrations**.
3. Select the menu and choose **Custom repositories**.
4. Add:
   - Repository: `https://github.com/tedr91/HA-Workday-Plus`
   - Category: `Integration`
5. Install **Workday Plus** from HACS.
6. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services**.
2. Click **Add Integration**.
3. Search for **Workday Plus**.
4. Complete the config flow options.

## Notes

- Domain: `workday_plus`
- Integration folder: `custom_components/workday_plus`
- Based on Home Assistant core `workday` logic and holiday handling.
