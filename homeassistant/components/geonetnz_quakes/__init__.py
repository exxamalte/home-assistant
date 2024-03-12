"""The GeoNet NZ Quakes integration."""
import logging

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    UnitOfLength,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.unit_conversion import DistanceConverter
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from .const import (
    CONF_MINIMUM_MAGNITUDE,
    CONF_MMI,
    DEFAULT_MINIMUM_MAGNITUDE,
    DEFAULT_MMI,
    DEFAULT_RADIUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FEED,
    PLATFORMS,
)
from .manager import GeonetnzQuakesFeedEntityManager

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Inclusive(CONF_LATITUDE, "coordinates"): cv.latitude,
                vol.Inclusive(CONF_LONGITUDE, "coordinates"): cv.longitude,
                vol.Optional(CONF_MMI, default=DEFAULT_MMI): vol.All(
                    vol.Coerce(int), vol.Range(min=-1, max=8)
                ),
                vol.Optional(CONF_RADIUS, default=DEFAULT_RADIUS): vol.Coerce(float),
                vol.Optional(
                    CONF_MINIMUM_MAGNITUDE, default=DEFAULT_MINIMUM_MAGNITUDE
                ): cv.positive_float,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): cv.time_period,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the GeoNet NZ Quakes component."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    latitude = conf.get(CONF_LATITUDE, hass.config.latitude)
    longitude = conf.get(CONF_LONGITUDE, hass.config.longitude)
    mmi = conf[CONF_MMI]
    scan_interval = conf[CONF_SCAN_INTERVAL]

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_LATITUDE: latitude,
                CONF_LONGITUDE: longitude,
                CONF_RADIUS: conf[CONF_RADIUS],
                CONF_MINIMUM_MAGNITUDE: conf[CONF_MINIMUM_MAGNITUDE],
                CONF_MMI: mmi,
                CONF_SCAN_INTERVAL: scan_interval,
            },
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up the GeoNet NZ Quakes component as config entry."""
    hass.data.setdefault(DOMAIN, {})
    feeds = hass.data[DOMAIN].setdefault(FEED, {})

    radius = config_entry.data[CONF_RADIUS]
    if hass.config.units is US_CUSTOMARY_SYSTEM:
        radius = DistanceConverter.convert(
            radius, UnitOfLength.MILES, UnitOfLength.KILOMETERS
        )
    # Create feed entity manager for all platforms.
    manager = GeonetnzQuakesFeedEntityManager(hass, config_entry, radius)
    feeds[config_entry.entry_id] = manager
    _LOGGER.debug("Feed entity manager added for %s", config_entry.entry_id)
    await manager.async_init()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an GeoNet NZ Quakes component config entry."""
    manager = hass.data[DOMAIN][FEED].pop(entry.entry_id)
    await manager.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
