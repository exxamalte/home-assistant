"""
Support for GeoRSS binary sensors.

Retrieves current events (typically incidents or alerts) through the GeoRSS
component and shows information on events filtered by distance to the HA
instance's location.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/binary_sensor.geo_rss_events/
"""
from functools import total_ordering

from homeassistant.components.binary_sensor import BinarySensorDevice
import logging

from homeassistant.components import geo_rss_events
from homeassistant.components.geo_rss_events import ATTR_CATEGORY, \
    ATTR_DISTANCE, ATTR_ENTRIES, ATTR_TITLE, CONF_SENSOR_CATEGORY, \
    CONF_SENSOR_EVENT_TYPE, CONF_SENSOR_NAME

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [geo_rss_events.DOMAIN]

CONF_SORT_ENTRIES_BY = 'sort_entries_by'
CONF_SORT_ENTRIES_REVERSE = 'sort_entries_reverse'

DEFAULT_SORT_ENTRIES_BY = None
DEFAULT_SORT_ENTRIES_REVERSE = False


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    _LOGGER.warning("config=%s, discovery_info=%s", config, discovery_info)
    add_devices([GeoRssEventBinarySensor(
        hass,
        discovery_info.get(CONF_SENSOR_NAME),
        discovery_info.get(CONF_SENSOR_EVENT_TYPE),
        discovery_info.get(CONF_SENSOR_CATEGORY))])
    return True


class GeoRssEventBinarySensor(BinarySensorDevice):
    """Representation of a binary sensor for the GeoRSS Events component."""

    def __init__(self, hass, name, event_type, category):
        """Initialize the GeoRSS Events binary sensor."""
        self._hass = hass
        self._name = name
        self._event_type = event_type
        self._category = category
        self._state = False
        self._state_attributes = {}
        hass.bus.listen(event_type, self._handle_event)

    @property
    def name(self):
        """Return the name of the binary sensor."""
        return self._name

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._state_attributes

    def _handle_event(self, call):
        """Handle incoming events from the GeoRSS Events components."""
        if ATTR_ENTRIES in call.data:
            entries = call.data[ATTR_ENTRIES]
            _LOGGER.debug("Entries received: %s", entries)
            # If category defined, remove entries not matching this category.
            if self._category:
                entries = [entry for entry in entries if
                           entry[ATTR_CATEGORY] == self._category]
            _LOGGER.debug("Entries with category %s: %s", self._category,
                          entries)
            # Read configuration values from current sensor state.
            current_state_attributes = self._hass.states.get(
                self.entity_id).attributes
            sort_entries_by = DEFAULT_SORT_ENTRIES_BY
            if CONF_SORT_ENTRIES_BY in current_state_attributes:
                sort_entries_by = current_state_attributes[
                    CONF_SORT_ENTRIES_BY]
            sort_entries_reverse = DEFAULT_SORT_ENTRIES_REVERSE
            if CONF_SORT_ENTRIES_REVERSE in current_state_attributes:
                sort_entries_reverse = current_state_attributes[
                    CONF_SORT_ENTRIES_REVERSE]
            # Sort entries if configured to do so.
            if sort_entries_by is not None:
                _LOGGER.debug("Sorting by %s", sort_entries_by)
                min_object = MinType()
                entries = sorted(entries,
                                 key=lambda my_entry:
                                 min_object if sort_entries_by not in my_entry
                                 or my_entry[sort_entries_by]
                                 is None else my_entry[sort_entries_by],
                                 reverse=sort_entries_reverse)
            _LOGGER.debug("Entries after sorting by %s: %s", sort_entries_by,
                          entries)
            # Compute the attributes from the filtered events.
            matrix = {}
            for entry in entries:
                matrix[entry[ATTR_TITLE]] = '{:.0f}km'.format(
                    entry[ATTR_DISTANCE])
            self._state_attributes = matrix
            # 'On' if at least one remaining entry.
            # 'Off' if no entries left after filtering.
            self._state = (len(entries) != 0)
            # Update state.
            self.schedule_update_ha_state()
        else:
            # Something went wrong - haven't received expected data.
            _LOGGER.warning("Event received but insufficient data found %s",
                            call.data)


@total_ordering
class MinType(object):
    """Represents an object type that is smaller than another when sorting."""

    def __le__(self, other):
        """Compare this objet to the other. Always true."""
        return True

    def __eq__(self, other):
        """Compare this object to the other."""
        return self is other
