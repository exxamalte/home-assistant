"""The tests for the binary sensor of the geo rss events component."""
import unittest
from unittest import mock

from homeassistant.components.binary_sensor.geo_rss_events import \
    setup_platform, CONF_SORT_ENTRIES_BY, CONF_SORT_ENTRIES_REVERSE
from homeassistant.components.geo_rss_events import CONF_SENSOR_NAME, \
    CONF_SENSOR_EVENT_TYPE, CONF_SENSOR_CATEGORY, ATTR_TITLE, ATTR_DISTANCE, \
    ATTR_CATEGORY, ATTR_NAME, ATTR_FEED_URL, ATTR_ENTRIES
from tests.common import get_test_home_assistant


class TestGeoRssEventsBinarySensor(unittest.TestCase):
    """Test the GeoRSS binary sensor."""

    DEVICES = []

    def add_devices(self, devices):
        """Mock add devices."""
        for device in devices:
            self.DEVICES.append(device)

    def setUp(self):
        """Initialize values for this testcase class."""
        self.hass = get_test_home_assistant()
        # Reset for this test.
        self.DEVICES = []

    def tearDown(self):
        """Stop everything that was started."""
        self.hass.stop()

    def setup_sensor(self, category="", include_entries_in_payload=True):
        """Set up sensor for test."""
        event_type = "event_type_1"
        name = "Name 1"
        discovery_info = {CONF_SENSOR_NAME: name,
                          CONF_SENSOR_EVENT_TYPE: event_type,
                          CONF_SENSOR_CATEGORY: category}
        setup_platform(self.hass, None, self.add_devices, discovery_info)
        self.assertEqual(len(self.DEVICES), 1)
        sensor = self.DEVICES[0]
        sensor.entity_id = "binary_sensor.name_1"
        self.assertEqual(name, sensor.name)
        self.assertEqual(False, sensor.is_on)
        # Send a summary event to the bus
        entries_summary = [{ATTR_TITLE: "Entry 1",
                            ATTR_DISTANCE: 25.0,
                            ATTR_CATEGORY: "Category 1"},
                           {ATTR_TITLE: "Entry 2",
                            ATTR_DISTANCE: 35.0,
                            ATTR_CATEGORY: "Category 1"},
                           {ATTR_TITLE: "Entry 3",
                            ATTR_DISTANCE: 15.0,
                            ATTR_CATEGORY: "Category 2"}
                           ]
        payload = {ATTR_NAME: name, ATTR_FEED_URL: "http://url"}
        if include_entries_in_payload:
            payload[ATTR_ENTRIES] = entries_summary
        self.hass.bus.fire(event_type, payload)
        self.hass.block_till_done()
        return sensor

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={}))
    def test_sensor(self, mock_get):
        """Test sensor with entries sent via event bus."""
        sensor = self.setup_sensor()
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 1': '25km', 'Entry 2': '35km',
                              'Entry 3': '15km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get', attributes={})
    def test_sensor_no_entries_sent(self, mock_get):
        """Test sensor without sending entries via event bus."""
        sensor = self.setup_sensor(include_entries_in_payload=False)
        self.assertEqual(False, sensor.is_on)
        self.assertEqual(str({}), str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={
                    CONF_SORT_ENTRIES_BY: ATTR_DISTANCE}))
    def test_sensor_sort_by(self, mock_get):
        """Test sensor with attributes sorted by existing attribute."""
        sensor = self.setup_sensor()
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 3': '15km', 'Entry 1': '25km',
                              'Entry 2': '35km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={
                    CONF_SORT_ENTRIES_BY: "does not exist"}))
    def test_sensor_sort_by_non_existent_attribute(self, mock_get):
        """Test senor with attributes sorted by non-existent attribute."""
        sensor = self.setup_sensor()
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 1': '25km', 'Entry 2': '35km',
                              'Entry 3': '15km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={
                    CONF_SORT_ENTRIES_BY: ATTR_DISTANCE,
                    CONF_SORT_ENTRIES_REVERSE: True}))
    def test_sensor_sort_by_reverse(self, mock_get):
        """Test sensor with attributes reverse sorted."""
        sensor = self.setup_sensor()
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 2': '35km', 'Entry 1': '25km',
                              'Entry 3': '15km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={}))
    def test_sensor_with_category(self, mock_get):
        """Test sensor with existing category."""
        sensor = self.setup_sensor(category="Category 1")
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 1': '25km', 'Entry 2': '35km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={}))
    def test_sensor_with_non_existent_category(self, mock_get):
        """Test sensor with non-existent category."""
        sensor = self.setup_sensor(category="does not exist")
        self.assertEqual(False, sensor.is_on)
        self.assertEqual(str({}), str(sensor.device_state_attributes))
