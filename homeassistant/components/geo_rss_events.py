"""
Generic GeoRSS events service.

Retrieves current events (typically incidents or alerts) in GeoRSS format, and
shows information on events filtered by distance to the HA instance's location
and grouped by category.

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
from homeassistant.const import CONF_URL, CONF_RADIUS, \
    CONF_UNIT_OF_MEASUREMENT, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.event import track_time_interval

REQUIREMENTS = ['feedparser==5.2.1', 'haversine==0.4.5']

_LOGGER = logging.getLogger(__name__)

ATTR_CATEGORY = 'category'
ATTR_DATE_PUBLISHED = 'date_published'
ATTR_DATE_UPDATED = 'date_updated'
ATTR_DISTANCE = 'distance'
ATTR_ID = 'id'
ATTR_TITLE = 'title'

CONF_CATEGORIES = 'categories'
CONF_CUSTOM_ATTRIBUTES = 'custom_attributes'
CONF_CUSTOM_ATTRIBUTES_NAME = 'name'
CONF_CUSTOM_ATTRIBUTES_REGEXP = 'regexp'
CONF_CUSTOM_ATTRIBUTES_SOURCE = 'source'
CONF_CUSTOM_FILTERS = 'custom_filters'
CONF_CUSTOM_FILTERS_ATTRIBUTE = 'attribute'
CONF_CUSTOM_FILTERS_REGEXP = 'regexp'

DEFAULT_ICON = 'mdi:alert'
DEFAULT_NAME = "Event Service"
DEFAULT_RADIUS_IN_KM = 20.0
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
DEFAULT_UNIT_OF_MEASUREMENT = 'Events'

DOMAIN = 'geo_rss_events'

CUSTOM_ATTRIBUTES_SCHEMA = vol.Schema({
    vol.Required(CONF_CUSTOM_ATTRIBUTES_NAME): cv.string,
    vol.Required(CONF_CUSTOM_ATTRIBUTES_SOURCE): cv.string,
    vol.Required(CONF_CUSTOM_ATTRIBUTES_REGEXP): cv.string,
})

CUSTOM_FILTERS_SCHEMA = vol.Schema({
    vol.Required(CONF_CUSTOM_FILTERS_ATTRIBUTE): cv.string,
    vol.Required(CONF_CUSTOM_FILTERS_REGEXP): cv.string,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.All(cv.ensure_list, [{
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_RADIUS, default=DEFAULT_RADIUS_IN_KM): vol.Coerce(
            float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL):
            cv.time_period,
        vol.Optional(CONF_CATEGORIES, default=[]):
            vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_CUSTOM_ATTRIBUTES,
                     default=[]): vol.All(cv.ensure_list,
                                          [CUSTOM_ATTRIBUTES_SCHEMA]),
        vol.Optional(CONF_CUSTOM_FILTERS,
                     default=[]): vol.All(cv.ensure_list,
                                          [CUSTOM_FILTERS_SCHEMA]),
    }])
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    """Set up the GeoRSS component."""
    home_latitude = hass.config.latitude
    home_longitude = hass.config.longitude
    data_file = hass.config.path("{}.pickle".format(DOMAIN))
    storage = StoredData(data_file)
    # Initialise each feed separately.
    for feed_config in config.get(DOMAIN):
        url = feed_config.get(CONF_URL)
        radius_in_km = feed_config.get(CONF_RADIUS)
        name = feed_config.get(CONF_NAME)
        scan_interval = feed_config.get(CONF_SCAN_INTERVAL)
        custom_attributes_definition = feed_config.get(CONF_CUSTOM_ATTRIBUTES)
        custom_filters_definition = feed_config.get(CONF_CUSTOM_FILTERS)
        #categories = config[DOMAIN].get(CONF_CATEGORIES)
        _LOGGER.debug("latitude=%s, longitude=%s, url=%s, radius=%s",
                      home_latitude, home_longitude, url, radius_in_km)
        GeoRssFeedManager(hass, storage, scan_interval, name, home_latitude,
                          home_longitude, url, radius_in_km,
                          custom_attributes_definition,
                          custom_filters_definition)
    return True


class GeoRssFeedManager(FeedManager):
    """Feed Manager for Geo RSS feeds."""

    def __init__(self, hass, storage, scan_interval, name, home_latitude,
                 home_longitude, url, radius_in_km,
                 custom_attributes_definition, custom_filters_definition):
        self._scan_interval = scan_interval
        super().__init__(url, hass, storage)
        self._name = name
        self._home_coordinates = [home_latitude, home_longitude]
        self._radius_in_km = radius_in_km
        self._custom_attributes_definition = custom_attributes_definition
        self._custom_filters_definition = custom_filters_definition
        entity_id = generate_entity_id('{}', name, hass=hass)
        self._event_type_id = entity_id
        self._feed_id = entity_id

    def _init_regular_updates(self, hass):
        """Schedule regular updates."""
        track_time_interval(hass, lambda now: self._update(),
                            self._scan_interval)

    def _filter_entries(self):
        """Filter entries by distance from home coordinates."""
        available_entries = self._feed.entries
        keep_entries = []
        _LOGGER.debug("%s entri(es) available in feed %s",
                      len(available_entries), self._url)
        for entry in available_entries:
            geometry = None
            if hasattr(entry, 'where'):
                geometry = entry.where
            elif hasattr(entry, 'geo_lat') and hasattr(entry, 'geo_long'):
                coordinates = (float(entry.geo_long), float(entry.geo_lat))
                point = namedtuple('Point', ['type', 'coordinates'])
                geometry = point('Point', coordinates)
            if geometry:
                distance = self.calculate_distance_to_geometry(geometry)
                if distance <= self._radius_in_km:
                    # Add distance value as a new attribute
                    entry.update({ATTR_DISTANCE: distance})
                    # Compute custom attributes.
                    for definition in self._custom_attributes_definition:
                        if hasattr(entry,
                                   definition[CONF_CUSTOM_ATTRIBUTES_SOURCE]):
                            # Use 'search' to allow for matching anywhere in
                            # the source attribute.
                            match = re.search(
                                definition[CONF_CUSTOM_ATTRIBUTES_REGEXP],
                                entry[definition[
                                    CONF_CUSTOM_ATTRIBUTES_SOURCE]])
                            entry.update({definition[
                                CONF_CUSTOM_ATTRIBUTES_NAME]: None if not match \
                                else match.group('custom_attribute')})
                        else:
                            _LOGGER.warning("No attribute '%s' found",
                                            definition[
                                                CONF_CUSTOM_ATTRIBUTES_SOURCE])
                            entry.update({definition[CONF_CUSTOM_ATTRIBUTES_NAME]: None})
                    # Run custom filters if defined.
                    keep_entry = True
                    if self._custom_filters_definition:
                        for definition in self._custom_filters_definition:
                            if hasattr(entry, definition[CONF_CUSTOM_FILTERS_ATTRIBUTE]):
                                match = re.match(
                                    definition[CONF_CUSTOM_FILTERS_REGEXP],
                                    entry.get(definition[
                                        CONF_CUSTOM_FILTERS_ATTRIBUTE]))
                                # If the attribute does not match, immediately return
                                # None value to eliminate entry, otherwise continue with
                                # the filter loop.
                                if not match:
                                    _LOGGER.debug(
                                        "Entry %s does not match filter %s",
                                        entry, definition)
                                    keep_entry = False
                                    break
                    if keep_entry:
                        keep_entries.append(entry)
        _LOGGER.debug("%s entries found nearby", len(keep_entries))
        self._feed.entries = keep_entries

    def calculate_distance_to_geometry(self, geometry):
        """Calculate the distance between HA and provided geometry."""
        distance = float("inf")
        if geometry.type == 'Point':
            distance = self.calculate_distance_to_point(geometry)
        elif geometry.type == 'Polygon':
            distance = self.calculate_distance_to_polygon(
                geometry.coordinates[0])
        else:
            _LOGGER.warning("Not yet implemented: %s", geometry.type)
        return distance

    def calculate_distance_to_point(self, point):
        """Calculate the distance between HA and the provided point."""
        # Swap coordinates to match: (lat, lon).
        coordinates = (point.coordinates[1], point.coordinates[0])
        return self.calculate_distance_to_coords(coordinates)

    def calculate_distance_to_coords(self, coordinates):
        """Calculate the distance between HA and the provided coordinates."""
        # Expecting coordinates in format: (lat, lon).
        from haversine import haversine
        distance = haversine(coordinates, self._home_coordinates)
        _LOGGER.debug("Distance from %s to %s: %s km", self._home_coordinates,
                      coordinates, distance)
        return distance

    def calculate_distance_to_polygon(self, polygon):
        """Calculate the distance between HA and the provided polygon."""
        distance = float("inf")
        # Calculate distance from polygon by calculating the distance
        # to each point of the polygon but not to each edge of the
        # polygon; should be good enough
        for polygon_point in polygon:
            coordinates = (polygon_point[1], polygon_point[0])
            distance = min(distance,
                           self.calculate_distance_to_coords(coordinates))
        _LOGGER.debug("Distance from %s to %s: %s km", self._home_coordinates,
                      polygon, distance)
        return distance
