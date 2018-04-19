"""The tests for the binary sensor of the geo rss events component."""
import unittest
from unittest import mock
from unittest.mock import patch

from homeassistant.components.binary_sensor.geo_rss_events import \
    setup_platform, CONF_SORT_ENTRIES_BY, CONF_SORT_ENTRIES_REVERSE
from homeassistant.components.geo_rss_events import ATTR_TITLE, \
    ATTR_DISTANCE, ATTR_CATEGORY, DOMAIN, ATTR_MANAGER, ATTR_CATEGORIES
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

    def test_setup(self):
        """Test general setup."""
        manager = mock.MagicMock()
        manager.configure_mock(feed_entries=[])
        manager.configure_mock(name="Name 1")
        self.hass.data[DOMAIN] = [{ATTR_MANAGER: manager,
                                   ATTR_CATEGORIES: None}]
        setup_platform(self.hass, None, self.add_devices, None)
        self.assertEqual(len(self.DEVICES), 1)
        sensor = self.DEVICES[0]
        self.assertEqual(False, sensor.is_on)
        self.hass.add_job(sensor.async_added_to_hass())
        self.hass.block_till_done()
        manager.add_update_listener.assert_called_once()
        args, kwargs = manager.add_update_listener.call_args
        callback = args[0]
        with patch("homeassistant.components.binary_sensor.geo_rss_events."
                   "GeoRssEventBinarySensor.schedule_update_ha_state") \
                as update_method:
            callback()
            update_method.assert_called_once()

    def setup_sensor(self, name, categories=None,
                     include_entries_in_payload=True):
        """Set up sensor for test."""
        manager = mock.MagicMock()
        if include_entries_in_payload:
            manager.configure_mock(feed_entries=[{ATTR_TITLE: "Entry 1",
                                                  ATTR_DISTANCE: 25.0,
                                                  ATTR_CATEGORY: "Category 1"},
                                                 {ATTR_TITLE: "Entry 2",
                                                  ATTR_DISTANCE: 35.0,
                                                  ATTR_CATEGORY: "Category 1"},
                                                 {ATTR_TITLE: "Entry 3",
                                                  ATTR_DISTANCE: 15.0,
                                                  ATTR_CATEGORY: "Category 2"}
                                                 ])
        else:
            manager.configure_mock(feed_entries=[])
        manager.configure_mock(name=name)
        self.hass.data[DOMAIN] = [{ATTR_MANAGER: manager,
                                   ATTR_CATEGORIES: categories}]
        setup_platform(self.hass, None, self.add_devices, None)
        self.assertEqual(len(self.DEVICES), 1)
        sensor = self.DEVICES[0]
        self.assertEqual(False, sensor.is_on)
        sensor.update()
        return sensor

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={}))
    # pylint: disable=unused-argument
    def test_sensor(self, mock_get):
        """Test sensor with entries sent via event bus."""
        name = "Name 1"
        sensor = self.setup_sensor(name)
        self.assertEqual(name, sensor.name)
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 1': '25km', 'Entry 2': '35km',
                              'Entry 3': '15km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get', attributes={})
    # pylint: disable=unused-argument
    def test_sensor_no_entries_sent(self, mock_get):
        """Test sensor without sending entries via event bus."""
        name = "Name 1"
        sensor = self.setup_sensor(name, include_entries_in_payload=False)
        self.assertEqual(name, sensor.name)
        self.assertEqual(False, sensor.is_on)
        self.assertEqual(str({}), str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={
                    CONF_SORT_ENTRIES_BY: ATTR_DISTANCE}))
    # pylint: disable=unused-argument
    def test_sensor_sort_by(self, mock_get):
        """Test sensor with attributes sorted by existing attribute."""
        name = "Name 1"
        sensor = self.setup_sensor(name)
        self.assertEqual(name, sensor.name)
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 3': '15km', 'Entry 1': '25km',
                              'Entry 2': '35km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={
                    CONF_SORT_ENTRIES_BY: "does not exist"}))
    # pylint: disable=unused-argument
    def test_sensor_sort_by_non_existent_attribute(self, mock_get):
        """Test senor with attributes sorted by non-existent attribute."""
        name = "Name 1"
        sensor = self.setup_sensor(name)
        self.assertEqual(name, sensor.name)
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 1': '25km', 'Entry 2': '35km',
                              'Entry 3': '15km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={
                    CONF_SORT_ENTRIES_BY: ATTR_DISTANCE,
                    CONF_SORT_ENTRIES_REVERSE: True}))
    # pylint: disable=unused-argument
    def test_sensor_sort_by_reverse(self, mock_get):
        """Test sensor with attributes reverse sorted."""
        name = "Name 1"
        sensor = self.setup_sensor(name)
        self.assertEqual(name, sensor.name)
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 2': '35km', 'Entry 1': '25km',
                              'Entry 3': '15km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={}))
    # pylint: disable=unused-argument
    def test_sensor_with_category(self, mock_get):
        """Test sensor with existing category."""
        name = "Name 1"
        category = "Category 1"
        sensor = self.setup_sensor(name, categories=[category])
        self.assertEqual(name + " " + category, sensor.name)
        self.assertEqual(True, sensor.is_on)
        self.assertEqual(str({'Entry 1': '25km', 'Entry 2': '35km'}),
                         str(sensor.device_state_attributes))

    @mock.patch('homeassistant.core.StateMachine.get',
                return_value=mock.Mock(attributes={}))
    # pylint: disable=unused-argument
    def test_sensor_with_non_existent_category(self, mock_get):
        """Test sensor with non-existent category."""
        name = "Name 1"
        category = "does not exist"
        sensor = self.setup_sensor(name, categories=[category])
        self.assertEqual(name + " " + category, sensor.name)
        self.assertEqual(False, sensor.is_on)
        self.assertEqual(str({}), str(sensor.device_state_attributes))
