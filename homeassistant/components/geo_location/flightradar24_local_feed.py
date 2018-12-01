"""
Flightradar24 Local Flights Feed platform.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/geo_location/flightradar24_local_feed/
"""
from datetime import timedelta
import logging
from typing import Optional

import voluptuous as vol

from homeassistant.components.geo_location import (
    PLATFORM_SCHEMA, GeoLocationEvent)
from homeassistant.const import (
    CONF_HOST, CONF_LATITUDE, CONF_LONGITUDE, CONF_PORT, CONF_RADIUS,
    CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_START)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect, dispatcher_send, async_dispatcher_send)
from homeassistant.helpers.event import async_track_time_interval

REQUIREMENTS = ['flightradar24_client==0.4a5']

_LOGGER = logging.getLogger(__name__)

ATTR_ALTITUDE = 'altitude'
ATTR_EXTERNAL_ID = 'external_id'
ATTR_SPEED = 'speed'
ATTR_SQUAWK = 'squawk'
ATTR_TRACK = 'track'
ATTR_VERTICAL_RATE = 'vertical_rate'
ATTR_UPDATED = 'updated'

CONF_MODE = 'mode'

DEFAULT_HOST = 'localhost'
DEFAULT_MODE = 'flightradar24'
DEFAULT_PORT = 8754
DEFAULT_RADIUS_IN_KM = 50.0
DEFAULT_UNIT_OF_MEASUREMENT = 'km'

SCAN_INTERVAL = timedelta(seconds=15)

SIGNAL_DELETE_ENTITY = 'flightradar24_local_feed_delete_{}'
SIGNAL_UPDATE_ENTITY = 'flightradar24_local_feed_update_{}'

SOURCE = 'flightradar24_local_feed'

VALID_MODES = ['flightradar24', 'dump1090']

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_LATITUDE): cv.latitude,
    vol.Optional(CONF_LONGITUDE): cv.longitude,
    vol.Optional(CONF_RADIUS, default=DEFAULT_RADIUS_IN_KM): vol.Coerce(float),
    vol.Optional(CONF_MODE, default=DEFAULT_MODE): vol.In(VALID_MODES),
    vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up the Flightradar24 Flights Feed platform."""
    scan_interval = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)
    mode = config.get(CONF_MODE)
    host = config[CONF_HOST]
    port = config[CONF_PORT]
    coordinates = (config.get(CONF_LATITUDE, hass.config.latitude),
                   config.get(CONF_LONGITUDE, hass.config.longitude))
    radius_in_km = config[CONF_RADIUS]
    # Initialize the entity manager.
    feed = Flightradar24FlightsFeedEntityManager(
        hass, async_add_entities, scan_interval, coordinates, mode, host, port,
        radius_in_km)

    async def start_feed_manager(event):
        """Start feed manager."""
        await feed.startup()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_feed_manager)


class Flightradar24FlightsFeedEntityManager:
    """Feed Entity Manager for Flightradar24 Flights feed."""

    def __init__(self, hass, async_add_entities, scan_interval, coordinates,
                 mode, host, port, radius_in_km):
        """Initialize the Feed Entity Manager."""
        self._hass = hass
        session = async_get_clientsession(hass)
        if mode == DEFAULT_MODE:
            from flightradar24_client.fr24_flights \
                import Flightradar24FlightsFeedManager
            self._feed_manager = Flightradar24FlightsFeedManager(
                self._generate_entity, self._update_entity,
                self._remove_entity, coordinates, filter_radius=radius_in_km,
                hostname=host, port=port, session=session, loop=hass.loop)
        else:
            from flightradar24_client.dump1090_aircrafts \
                import Dump1090AircraftsFeedManager
            self._feed_manager = Dump1090AircraftsFeedManager(
                self._generate_entity, self._update_entity,
                self._remove_entity, coordinates, filter_radius=radius_in_km,
                hostname=host, port=port, session=session, loop=hass.loop)
        self._async_add_entities = async_add_entities
        self._scan_interval = scan_interval

    async def startup(self):
        """Start up this manager."""
        await self._feed_manager.update(None)
        self._init_regular_updates()

    def _init_regular_updates(self):
        """Schedule regular updates at the specified interval."""
        async_track_time_interval(
            self._hass, self._feed_manager.update,
            self._scan_interval)

    def get_entry(self, external_id):
        """Get feed entry by external id."""
        return self._feed_manager.feed_entries.get(external_id)

    async def _generate_entity(self, external_id):
        """Generate new entity."""
        new_entity = Flightradar24Flight(self, external_id)
        # Add new entities to HA.
        self._async_add_entities([new_entity], True)

    async def _update_entity(self, external_id):
        """Update entity."""
        async_dispatcher_send(
            self._hass, SIGNAL_UPDATE_ENTITY.format(external_id))

    async def _remove_entity(self, external_id):
        """Remove entity."""
        async_dispatcher_send(
            self._hass, SIGNAL_DELETE_ENTITY.format(external_id))


class Flightradar24Flight(GeoLocationEvent):
    """This represents an external Flightradar24 flight."""

    def __init__(self, feed_manager, external_id):
        """Initialize entity with data from feed entry."""
        self._feed_manager = feed_manager
        self._external_id = external_id
        self._name = None
        self._distance = None
        self._latitude = None
        self._longitude = None
        self._altitude = None
        self._speed = None
        self._track = None
        self._updated = None
        self._squawk = None
        self._vert_rate = None
        self._remove_signal_delete = None
        self._remove_signal_update = None

    async def async_added_to_hass(self):
        """Call when entity is added to hass."""
        self._remove_signal_delete = async_dispatcher_connect(
            self.hass, SIGNAL_DELETE_ENTITY.format(self._external_id),
            self._delete_callback)
        self._remove_signal_update = async_dispatcher_connect(
            self.hass, SIGNAL_UPDATE_ENTITY.format(self._external_id),
            self._update_callback)

    @callback
    def _delete_callback(self):
        """Remove this entity."""
        self._remove_signal_delete()
        self._remove_signal_update()
        self.hass.async_create_task(self.async_remove())

    @callback
    def _update_callback(self):
        """Call update method."""
        self.async_schedule_update_ha_state(True)

    @property
    def should_poll(self):
        """No polling needed for Flightradar24 events."""
        return False

    async def async_update(self):
        """Update this entity from the data held in the feed manager."""
        _LOGGER.debug("Updating %s", self._external_id)
        feed_entry = self._feed_manager.get_entry(self._external_id)
        if feed_entry:
            self._update_from_feed(feed_entry)

    def _update_from_feed(self, feed_entry):
        """Update the internal state from the provided feed entry."""
        self._name = self._external_id \
            if not feed_entry.callsign else feed_entry.callsign
        self._distance = feed_entry.distance_to_home
        self._latitude = feed_entry.coordinates[0]
        self._longitude = feed_entry.coordinates[1]
        self._altitude = feed_entry.altitude
        self._speed = feed_entry.speed
        self._track = feed_entry.track
        self._squawk = feed_entry.squawk
        self._vert_rate = feed_entry.vert_rate
        self._updated = feed_entry.updated

    @property
    def source(self) -> str:
        """Return source value of this external event."""
        return SOURCE

    @property
    def name(self) -> Optional[str]:
        """Return the name of the entity."""
        return self._name

    @property
    def distance(self) -> Optional[float]:
        """Return distance value of this external event."""
        return self._distance

    @property
    def latitude(self) -> Optional[float]:
        """Return latitude value of this external event."""
        return self._latitude

    @property
    def longitude(self) -> Optional[float]:
        """Return longitude value of this external event."""
        return self._longitude

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return DEFAULT_UNIT_OF_MEASUREMENT

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attributes = {}
        for key, value in (
                (ATTR_EXTERNAL_ID, self._external_id),
                (ATTR_ALTITUDE, self._altitude),
                (ATTR_SPEED, self._speed),
                (ATTR_TRACK, self._track),
                (ATTR_SQUAWK, self._squawk),
                (ATTR_VERTICAL_RATE, self._vert_rate),
                (ATTR_UPDATED, self._updated),
        ):
            if value or isinstance(value, bool):
                attributes[key] = value
        return attributes
