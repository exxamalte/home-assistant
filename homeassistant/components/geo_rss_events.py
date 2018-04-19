"""
Generic GeoRSS events service.

Retrieves current events (typically incidents or alerts) in GeoRSS format, and
publishes information on events filtered by distance to the HA instance's
location and grouped by category onto the HA event bus.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/geo_rss_events/
"""
import logging
from collections import namedtuple
from datetime import timedelta
import re

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.feedreader import StoredData, FeedManager
from homeassistant.const import CONF_URL, CONF_RADIUS, CONF_NAME, \
    CONF_SCAN_INTERVAL
from homeassistant.helpers import discovery
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.event import track_time_interval

REQUIREMENTS = ['feedparser==5.2.1', 'haversine==0.4.5']

_LOGGER = logging.getLogger(__name__)

ATTR_CATEGORIES = "categories"
ATTR_CATEGORY = 'category'
ATTR_DISTANCE = 'distance'
ATTR_MANAGER = "manager"
ATTR_TITLE = 'title'

CONF_CATEGORIES = 'categories'
CONF_ATTRIBUTES = 'attributes'
CONF_ATTRIBUTES_NAME = 'name'
CONF_ATTRIBUTES_REGEXP = 'regexp'
CONF_ATTRIBUTES_SOURCE = 'source'
CONF_CUSTOM_ATTRIBUTE = 'custom_attribute'
CONF_FILTERS = 'filters'
CONF_FILTERS_ATTRIBUTE = 'attribute'
CONF_FILTERS_REGEXP = 'regexp'
CONF_SENSOR_CATEGORY = 'category'
CONF_SENSOR_EVENT_TYPE = 'event_type'
CONF_SENSOR_NAME = 'name'

DEFAULT_NAME = "Event Service"
DEFAULT_RADIUS_IN_KM = 20.0
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

DOMAIN = 'geo_rss_events'

ATTRIBUTES_SCHEMA = vol.Schema({
    vol.Required(CONF_ATTRIBUTES_NAME): cv.string,
    vol.Required(CONF_ATTRIBUTES_SOURCE): cv.string,
    vol.Required(CONF_ATTRIBUTES_REGEXP): cv.string,
})

FILTERS_SCHEMA = vol.Schema({
    vol.Required(CONF_FILTERS_ATTRIBUTE): cv.string,
    vol.Required(CONF_FILTERS_REGEXP): cv.string,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.All(cv.ensure_list, [{
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_RADIUS, default=DEFAULT_RADIUS_IN_KM):
            vol.Coerce(float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL):
            cv.time_period,
        vol.Optional(CONF_CATEGORIES, default=[]):
            vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_ATTRIBUTES, default=[]):
            vol.All(cv.ensure_list, [ATTRIBUTES_SCHEMA]),
        vol.Optional(CONF_FILTERS, default=[]):
            vol.All(cv.ensure_list, [FILTERS_SCHEMA]),
    }])
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    """Set up the GeoRSS component."""
    home_latitude = hass.config.latitude
    home_longitude = hass.config.longitude
    data_file = hass.config.path("{}.pickle".format(DOMAIN))
    storage = StoredData(data_file)
    # Initialise each feed separately.
    feeds = []
    for feed_config in config.get(DOMAIN):
        url = feed_config.get(CONF_URL)
        radius_in_km = feed_config.get(CONF_RADIUS)
        name = feed_config.get(CONF_NAME)
        scan_interval = feed_config.get(CONF_SCAN_INTERVAL)
        categories = feed_config.get(CONF_CATEGORIES)
        attributes_definition = feed_config.get(CONF_ATTRIBUTES)
        filters_definition = feed_config.get(CONF_FILTERS)
        _LOGGER.debug("latitude=%s, longitude=%s, url=%s, radius=%s",
                      home_latitude, home_longitude, url, radius_in_km)
        # Intantiate feed manager for each configured feed.
        manager = GeoRssFeedManager(hass, storage, scan_interval, name,
                                    home_latitude, home_longitude, url,
                                    radius_in_km, attributes_definition,
                                    filters_definition)
        feed = {ATTR_MANAGER: manager, ATTR_CATEGORIES: categories}
        feeds.append(feed)
    hass.data[DOMAIN] = feeds
    # And load sensors.
    discovery.load_platform(hass, "binary_sensor", DOMAIN, None, config)
    return True


class GeoRssFeedManager(FeedManager):
    """Feed Manager for Geo RSS feeds."""

    def __init__(self, hass, storage, scan_interval, name, home_latitude,
                 home_longitude, url, radius_in_km, attributes_definition,
                 filters_definition):
        """Initialize the GeoRSS Feed Manager."""
        self._scan_interval = scan_interval
        super().__init__(url, hass, storage)
        self._name = name
        self._home_coordinates = [home_latitude, home_longitude]
        self._geo_distance_helper = GeoDistanceHelper(self._home_coordinates)
        self._radius_in_km = radius_in_km
        self._attributes_definition = attributes_definition
        self._filters_definition = filters_definition
        entity_id = generate_entity_id('{}', name, hass=hass)
        self._event_type = entity_id
        self._feed_id = entity_id
        self._update_listeners = []

    @property
    def name(self):
        """Return the name."""
        return self._name

    @property
    def feed_entries(self):
        """Return the current set of feed entries."""
        return [] if not hasattr(self._feed, 'entries') else self._feed.entries

    def _init_regular_updates(self, hass):
        """Schedule regular updates based on configured time interval."""
        track_time_interval(hass, lambda now: self._update(),
                            self._scan_interval)

    def _filter_entries(self):
        """Filter entries by distance from home coordinates."""
        available_entries = self._feed.entries
        keep_entries = []
        for entry in available_entries:
            geometry = None
            if hasattr(entry, 'where'):
                geometry = entry.where
            elif hasattr(entry, 'geo_lat') and hasattr(entry, 'geo_long'):
                coordinates = (float(entry.geo_long), float(entry.geo_lat))
                point = namedtuple('Point', ['type', 'coordinates'])
                geometry = point('Point', coordinates)
            if geometry:
                distance = self._geo_distance_helper.distance_to_geometry(
                    geometry)
                if distance <= self._radius_in_km:
                    # Add distance value as a new attribute
                    entry.update({ATTR_DISTANCE: distance})
                    # Compute custom attributes.
                    for definition in self._attributes_definition:
                        if hasattr(entry, definition[CONF_ATTRIBUTES_SOURCE]):
                            # Use 'search' to allow for matching anywhere in
                            # the source attribute.
                            match = re.search(
                                definition[CONF_ATTRIBUTES_REGEXP],
                                entry[definition[CONF_ATTRIBUTES_SOURCE]])
                            entry.update({definition[CONF_ATTRIBUTES_NAME]:
                                         '' if not match else match.group(
                                                  CONF_CUSTOM_ATTRIBUTE)})
                        else:
                            _LOGGER.warning("No attribute '%s' found",
                                            definition[CONF_ATTRIBUTES_SOURCE])
                            # Add empty string to allow for applying filter
                            # rules.
                            entry.update(
                                {definition[CONF_ATTRIBUTES_NAME]: ''})
                    # Run custom filters if defined.
                    keep_entry = True
                    if self._filters_definition:
                        for definition in self._filters_definition:
                            if hasattr(entry, definition[
                                    CONF_FILTERS_ATTRIBUTE]):
                                match = re.match(
                                    definition[CONF_FILTERS_REGEXP],
                                    entry.get(
                                        definition[CONF_FILTERS_ATTRIBUTE]))
                                # If the attribute does not match, immediately
                                # drop out of loop to eliminate the entry.
                                if not match:
                                    _LOGGER.debug(
                                        "Entry %s does not match filter %s",
                                        entry, definition)
                                    keep_entry = False
                                    break
                            else:
                                # Discard entry because it does not contain
                                # attribute
                                _LOGGER.debug(
                                    "Entry %s does not contain attribute %s",
                                    entry, definition[CONF_FILTERS_ATTRIBUTE])
                                keep_entry = False
                                break
                    if keep_entry:
                        keep_entries.append(entry)
        _LOGGER.debug("%s entries found nearby after filtering",
                      len(keep_entries))
        self._feed.entries = keep_entries
        # Update connected sensors.
        for listener in self._update_listeners:
            listener()

    def add_update_listener(self, listener):
        """Add a listener for update notifications."""
        self._update_listeners.append(listener)


class GeoDistanceHelper(object):
    """Helper to calculate distances between geometries."""

    def __init__(self, home_coordinates):
        """Initialize the geo distance helper."""
        self._home_coordinates = home_coordinates

    def distance_to_geometry(self, geometry):
        """Calculate the distance between HA's home coordinates and the
        provided geometry."""
        distance = float("inf")
        if geometry.type == 'Point':
            distance = self._distance_to_point(geometry)
        elif geometry.type == 'Polygon':
            distance = self._distance_to_polygon(geometry.coordinates[0])
        else:
            _LOGGER.warning("Not yet implemented: %s", geometry.type)
        return distance

    def _distance_to_point(self, point):
        """Calculate the distance between HA and the provided point."""
        # Swap coordinates to match: (lat, lon).
        coordinates = (point.coordinates[1], point.coordinates[0])
        return self._distance_to_coords(coordinates)

    def _distance_to_coords(self, coordinates):
        """Calculate the distance between HA and the provided coordinates."""
        # Expecting coordinates in format: (lat, lon).
        from haversine import haversine
        distance = haversine(coordinates, self._home_coordinates)
        _LOGGER.debug("Distance from %s to %s: %s km", self._home_coordinates,
                      coordinates, distance)
        return distance

    def _distance_to_polygon(self, polygon):
        """Calculate the distance between HA and the provided polygon."""
        distance = float("inf")
        # Calculate distance from polygon by calculating the distance
        # to each point of the polygon but not to each edge of the
        # polygon; should be good enough
        for polygon_point in polygon:
            coordinates = (polygon_point[1], polygon_point[0])
            distance = min(distance, self._distance_to_coords(coordinates))
        _LOGGER.debug("Distance from %s to %s: %s km", self._home_coordinates,
                      polygon, distance)
        return distance
