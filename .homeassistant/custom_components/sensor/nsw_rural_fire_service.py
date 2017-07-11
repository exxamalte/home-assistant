"""
Retrieve current incidents from NSW Rural Fire Service (www.rfs.nsw.gov.au/fire-information/fires-near-me),
and show information on incidents filtered by distance to the HA instance's
location.

Alert levels
* Emergency Warning
* Watch and Act
* Advice
* Information (aka "Not Applicable")

Example configuration:

sensor:
  - platform: nsw_rural_fire_service
    radius: 15

"""
import asyncio
import logging
import json
from datetime import timedelta

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor.rest import RestData
from homeassistant.const import (STATE_UNKNOWN, CONF_SCAN_INTERVAL)
from homeassistant.helpers.entity import Entity, async_generate_entity_id
from homeassistant.helpers.event import async_track_time_interval

REQUIREMENTS = ['geojson==1.3.5', 'haversine==0.4.5']
# 'shapely>=1.5'

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'nsw_rural_fire_service_incidents'
ENTITY_ID_FORMAT = 'sensor.' + DOMAIN + '_{}'
INCIDENTS = 'incidents'
ICON = 'mdi:fire'

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=5)

CONF_URL = 'url'
CONF_RADIUS = 'radius'

DEFAULT_NAME = 'NSW Rural Fire Service'
DEFAULT_URL = 'http://www.rfs.nsw.gov.au/feeds/majorIncidents.json'
DEFAULT_RADIUS_IN_KM = 20.0

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_URL, default=DEFAULT_URL): cv.string,
    vol.Optional(CONF_RADIUS, default=DEFAULT_RADIUS_IN_KM): vol.Coerce(float),
})

ALERT_LEVELS = ['Emergency Warning', 'Watch and Act', 'Advice', 'Information']


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):

    # Grab location from config
    home_latitude = hass.config.latitude
    home_longitude = hass.config.longitude
    url = config.get(CONF_URL)
    radius_in_km = config.get(CONF_RADIUS)
    interval_in_seconds = config.get(CONF_SCAN_INTERVAL) or timedelta(minutes=5)

    if None in (home_latitude, home_longitude):
        _LOGGER.error("Latitude or longitude not set in Home Assistant config")
        return False

    _LOGGER.debug("latitude=%s, longitude=%s, url=%s, radius=%s", home_latitude,
                 home_longitude, url, radius_in_km)

    # create all sensors
    devices = []
    devices_by_alert_level = {}
    for alert_level in ALERT_LEVELS:
        device = NswRuralFireServiceSensor(hass, alert_level, [])
        devices.append(device)
        devices_by_alert_level[alert_level] = device
    async_add_devices(devices)

    # initialise access to web resource
    rest = RestData('GET', url, None, '', '', True)
    updater = NswRuralFireServiceUpdater(hass, rest, home_latitude, home_longitude, url, radius_in_km,
                                         devices_by_alert_level)
    async_track_time_interval(hass, updater.async_update, interval_in_seconds)
    yield from updater.async_update()
    return True


class NswRuralFireServiceSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, hass, alert_level, incidents):
        """Initialize the sensor."""
        self.hass = hass
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, alert_level,
                                                  hass=hass)
        self._alert_level = alert_level
        self._state = incidents

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._alert_level

    @property
    def state(self):
        """Return the state of the sensor."""
        if isinstance(self._state, list):
            return len(self._state)
        else:
            return self._state

    @state.setter
    def state(self, value):
        self._state = value

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return INCIDENTS

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return ICON

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        matrix = {}
        for incident in self._state:
            # matrix[incident.title] = incident.type + ", " + incident.status
            matrix[incident.title] = incident.status
        return matrix


class NswRuralFireServiceUpdater:
    """Provides access to GeoJSON and creates and updates UI devices."""

    def __init__(self, hass, rest, home_latitude, home_longitude, url,
                 radius_in_km, devices_by_alert_level):
        """Initialize the sensor."""
        self._hass = hass
        self._rest = rest
        self._home_latitude = home_latitude
        self._home_longitude = home_longitude
        self._home_coordinates = [home_longitude, home_latitude]
        self._url = url
        self._radius_in_km = radius_in_km
        self._state = STATE_UNKNOWN
        self._devices_by_alert_level = devices_by_alert_level

    @asyncio.coroutine
    def async_update(self, *_):
        import geojson
        """retrieve data"""
        self._rest.update()
        value = self._rest.data
        # _LOGGER.debug("data retrieved=%s", value)
        if value is None:
            _LOGGER.warning("No data retrieved from %s", self._url)
        else:
            incidents = []
            feature_collection = geojson.loads(value)
            for feature in feature_collection.features:
                # print(feature)
                geometry = feature.geometry
                # _LOGGER.info(geometry)
                distance = self.calculate_distance_to_geometry(geometry)
                if distance <= self._radius_in_km:
                    incident = self.create_incident(distance, feature)
                    # _LOGGER.info(incident)
                    incidents.append(incident)
            value = incidents
            # group incidents by alert level
            incidents_by_alert_level = {}
            for incident in value:
                if incident.alert_level in incidents_by_alert_level:
                    incidents_by_alert_level[incident.alert_level].append(incident)
                else:
                    incidents_by_alert_level[incident.alert_level] = [incident]
            _LOGGER.info("Incidents by alert level: %s", incidents_by_alert_level)
            # set new state (incidents) on devices
            tasks = []
            for alert_level in incidents_by_alert_level.keys():
                # update existing device with new list of incidents
                device = self._devices_by_alert_level[alert_level]
                device.state = incidents_by_alert_level[alert_level]
                tasks.append(device.async_update_ha_state())
            _LOGGER.info("Devices by alert level: %s", self._devices_by_alert_level)
            if tasks:
                yield from asyncio.wait(tasks, loop=self._hass.loop)

    @staticmethod
    def create_incident(distance, feature):
        incident = Incident(feature.properties['category'],
                            feature.properties['title'],
                            feature.properties['guid'],
                            feature.properties['pubDate'],
                            feature.properties['description'], distance)
        # extract data from description
        description_items = feature.properties['description'].split("<br />")
        # TODO: how to deal with: "MAJOR FIRE UPDATE AS AT 6 Nov 2016 7:53AM: <a href='http://www.rfs.nsw.gov.au/fire-information/major-fire-updates/mfu?id=576' target='_blank'> More information</a>"?
        for item in description_items:
            try:
                item_parts = item.split(":", 1)
                key = item_parts[0].strip()
                value = item_parts[1].strip()
                if key == 'ALERT LEVEL':
                    # transform this into something useful
                    if value == 'Not Applicable':
                        value = 'Information'
                    incident.alert_level = value
                elif key == 'LOCATION':
                    incident.location = value
                elif key == 'COUNCIL AREA':
                    incident.council_area = value
                elif key == 'STATUS':
                    incident.status = value
                elif key == 'TYPE':
                    incident.type = value
                elif key == 'FIRE':
                    incident.fire = value
                elif key == 'SIZE':
                    incident.size = value
                elif key == 'RESPONSIBLE AGENCY':
                    incident.responsible_agency = value
                elif key == 'UPDATED':
                    incident.updated = value
            except Exception as e:
                _LOGGER.warning("Unable to parse info from '%s': %s", item, e)
        return incident

    def calculate_distance_to_geometry(self, geometry):
        from geojson import Point, GeometryCollection
        distance = float("inf")
        if type(geometry) is Point:
            # print("Point")
            distance = self.calculate_distance_to_point(geometry)
        elif type(geometry) is GeometryCollection:
            # print("GeometryCollection")
            distance = self.calculate_distance_to_geometry_collection(geometry)
        else:
            _LOGGER.info("Not yet implemented: %s", type(geometry))
        return distance

    def calculate_distance_to_point(self, point):
        # from shapely.geometry import shape
        from haversine import haversine
        coordinates = point.coordinates
        distance = haversine(coordinates, self._home_coordinates)
        _LOGGER.debug("Distance from %s to %s: %s km", self._home_coordinates,
                      coordinates, distance)
        return distance

    def calculate_distance_to_geometry_collection(self, geometry_collection):
        geometries = geometry_collection.geometries
        distance = float("inf")
        for geometry in geometries:
            distance = min(distance,
                           self.calculate_distance_to_geometry(geometry))
        return distance


class Incident(object):
    """Class for storing incidents retrieved."""

    def __init__(self, category, title, guid, pub_date, description, distance):
        """Initialize the data object."""
        self._category = category
        self._title = title
        self._guid = guid
        self._pub_date = pub_date
        self._description = description
        self._distance = distance
        self._alert_level = None
        self._location = None
        self._council_area = None
        self._status = None
        self._type = None
        self._fire = None
        self._size = None
        self._responsible_agency = None
        self._updated = None

    @property
    def category(self):
        return self._category

    @property
    def title(self):
        return self._title

    @property
    def pub_date(self):
        return self._pub_date

    @property
    def description(self):
        return self._description

    @property
    def distance(self):
        return self._distance

    @property
    def alert_level(self):
        return self._alert_level

    @alert_level.setter
    def alert_level(self, value):
        self._alert_level = value

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, value):
        self._location = value

    @property
    def council_area(self):
        return self._council_area

    @council_area.setter
    def council_area(self, value):
        self._council_area = value

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, value):
        self._type = value

    @property
    def fire(self):
        return self._fire

    @fire.setter
    def fire(self, value):
        self._fire = value

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, value):
        self._size = value

    @property
    def responsible_agency(self):
        return self._responsible_agency

    @responsible_agency.setter
    def responsible_agency(self, value):
        self._responsible_agency = value

    @property
    def updated(self):
        return self._updated

    @updated.setter
    def updated(self, value):
        self._updated = value

    def __str__(self, *args, **kwargs):
        return json.dumps(self, default=lambda obj: vars(obj), indent=1)
