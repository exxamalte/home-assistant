"""The GeoNet NZ Quakes entity manager."""
from datetime import timedelta
import logging

from aio_geojson_geonetnz_quakes import GeonetnzQuakesFeedManager

from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_MINIMUM_MAGNITUDE,
    CONF_MMI,
    DEFAULT_FILTER_TIME_INTERVAL,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


class GeonetnzQuakesFeedEntityManager:
    """Feed Entity Manager for GeoNet NZ Quakes feed."""

    def __init__(self, hass, config_entry, radius_in_km):
        """Initialize the Feed Entity Manager."""
        self._hass = hass
        self._config_entry = config_entry
        coordinates = (
            config_entry.data[CONF_LATITUDE],
            config_entry.data[CONF_LONGITUDE],
        )
        websession = aiohttp_client.async_get_clientsession(hass)
        self._feed_manager = GeonetnzQuakesFeedManager(
            websession,
            self._generate_entity,
            self._update_entity,
            self._remove_entity,
            coordinates,
            mmi=config_entry.data[CONF_MMI],
            filter_radius=radius_in_km,
            filter_minimum_magnitude=config_entry.data[CONF_MINIMUM_MAGNITUDE],
            filter_time=DEFAULT_FILTER_TIME_INTERVAL,
            status_callback=self._status_update,
        )
        self._config_entry_id = config_entry.entry_id
        self._scan_interval = timedelta(seconds=config_entry.data[CONF_SCAN_INTERVAL])
        self._track_time_remove_callback = None
        self._status_info = None
        self.listeners = []

    async def async_init(self):
        """Schedule initial and regular updates based on configured time interval."""

        await self._hass.config_entries.async_forward_entry_setups(
            self._config_entry, PLATFORMS
        )

        async def update(event_time):
            """Update."""
            await self.async_update()

        # Trigger updates at regular intervals.
        self._track_time_remove_callback = async_track_time_interval(
            self._hass, update, self._scan_interval
        )

        _LOGGER.debug("Feed entity manager initialized")

    async def async_update(self):
        """Refresh data."""
        await self._feed_manager.update()
        _LOGGER.debug("Feed entity manager updated")

    async def async_stop(self):
        """Stop this feed entity manager from refreshing."""
        for unsub_dispatcher in self.listeners:
            unsub_dispatcher()
        self.listeners = []
        if self._track_time_remove_callback:
            self._track_time_remove_callback()
        _LOGGER.debug("Feed entity manager stopped")

    @callback
    def async_event_new_entity(self):
        """Return manager specific event to signal new entity."""
        return f"geonetnz_quakes_new_geolocation_{self._config_entry_id}"

    def get_entry(self, external_id):
        """Get feed entry by external id."""
        return self._feed_manager.feed_entries.get(external_id)

    def status_info(self):
        """Return latest status update info received."""
        return self._status_info

    async def _generate_entity(self, external_id):
        """Generate new entity."""
        async_dispatcher_send(
            self._hass,
            self.async_event_new_entity(),
            self,
            self._config_entry.unique_id,
            external_id,
        )

    async def _update_entity(self, external_id):
        """Update entity."""
        async_dispatcher_send(self._hass, f"geonetnz_quakes_update_{external_id}")

    async def _remove_entity(self, external_id):
        """Remove entity."""
        async_dispatcher_send(self._hass, f"geonetnz_quakes_delete_{external_id}")

    async def _status_update(self, status_info):
        """Propagate status update."""
        _LOGGER.debug("Status update received: %s", status_info)
        self._status_info = status_info
        async_dispatcher_send(
            self._hass, f"geonetnz_quakes_status_{self._config_entry_id}"
        )
