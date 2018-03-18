"""The tests for the geo rss events component."""
import unittest

from homeassistant.components.feedreader import StoredData
from homeassistant.const import CONF_NAME, CONF_RADIUS, CONF_URL, \
    EVENT_HOMEASSISTANT_START
from homeassistant.core import callback
from homeassistant.setup import setup_component
from tests.common import load_fixture, get_test_home_assistant
import homeassistant.components.geo_rss_events as geo_rss_events

URL = 'http://geo.rss.local/geo_rss_events.xml'
VALID_CONFIG_1 = {
    geo_rss_events.DOMAIN: []
}
VALID_CONFIG_2 = {
    geo_rss_events.DOMAIN: [{
        CONF_NAME: 'Name 1',
        CONF_URL: URL,
        CONF_RADIUS: 100.0
    }]
}


class TestGeoRssEventsComponent(unittest.TestCase):
    """Test the GeoRss component."""

    def setUp(self):
        """Initialize values for this testcase class."""
        self.hass = get_test_home_assistant()

    def tearDown(self):
        """Stop everything that was started."""
        self.hass.stop()

    def test_setup_empty_feeds_list(self):
        """Test the general setup of this component."""
        self.assertTrue(setup_component(self.hass, geo_rss_events.DOMAIN,
                                        VALID_CONFIG_1))

    def test_setup_one_feed(self):
        """Test the general setup of this component."""
        self.assertTrue(setup_component(self.hass, geo_rss_events.DOMAIN,
                                        VALID_CONFIG_2))

    def setup_data(self, url='url', name=geo_rss_events.DEFAULT_NAME,
                   scan_interval=geo_rss_events.DEFAULT_SCAN_INTERVAL,
                   attributes_definition=None, filters_definition=None):
        """Set up data object for use by sensors."""
        if attributes_definition is None:
            attributes_definition = []
        home_latitude = -33.865
        home_longitude = 151.209444
        data_file = self.hass.config.path("{}.pickle".format(
            geo_rss_events.DOMAIN))
        storage = StoredData(data_file)
        radius_in_km = 500
        data = geo_rss_events.GeoRssFeedManager(self.hass, storage,
                                                scan_interval, name,
                                                home_latitude,
                                                home_longitude, url,
                                                radius_in_km,
                                                attributes_definition,
                                                filters_definition)
        return data

    def prepare_test(self, attributes_definition=None,
                     filters_definition=None):
        """Run generic test with a configuration as provided."""
        events = []

        @callback
        def record_event(event):
            """Add recorded event to set."""
            events.append(event)

        name = "Name 1"
        feed_id = "name_1"
        self.hass.bus.listen(feed_id, record_event)
        # Loading raw data from fixture and plug in to data object as URL
        # works since the third-party feedparser library accepts a URL
        # as well as the actual data.
        raw_data = load_fixture('geo_rss_events.xml')
        data = self.setup_data(raw_data, name=name,
                               attributes_definition=attributes_definition,
                               filters_definition=filters_definition)
        assert data._event_type == feed_id
        assert data._feed_id == feed_id
        # Artificially trigger update.
        self.hass.bus.fire(EVENT_HOMEASSISTANT_START)
        # Collect events
        self.hass.block_till_done()
        return events

    def test_update_component(self):
        """Test updating component object."""
        events = self.prepare_test()
        # Check entries
        self.assertEqual(4, len(events))
        assert events[0].data.get('title') == "Title 1"
        self.assertAlmostEqual(
            events[0].data.get(geo_rss_events.ATTR_DISTANCE), 116.782, 0)
        assert events[1].data.get('title') == "Title 2"
        self.assertAlmostEqual(
            events[1].data.get(geo_rss_events.ATTR_DISTANCE), 301.737, 0)
        assert events[2].data.get('title') == "Title 3"
        self.assertAlmostEqual(
            events[2].data.get(geo_rss_events.ATTR_DISTANCE), 203.786, 0)
        assert events[3].data.get('title') == "Title 6"
        self.assertAlmostEqual(
            events[3].data.get(geo_rss_events.ATTR_DISTANCE), 48.06, 0)

    def test_attributes(self):
        """Test extracting a custom attribute."""
        attributes_definition = [{
            geo_rss_events.CONF_ATTRIBUTES_NAME: 'title_index',
            geo_rss_events.CONF_ATTRIBUTES_SOURCE: 'title',
            geo_rss_events.CONF_ATTRIBUTES_REGEXP:
                '(?P<' + geo_rss_events.CONF_CUSTOM_ATTRIBUTE + '>\d+)'
        }]
        events = self.prepare_test(attributes_definition=attributes_definition)
        # Check entries
        self.assertEqual(4, len(events))
        assert events[0].data.get('title_index') == '1'
        assert events[1].data.get('title_index') == '2'
        assert events[2].data.get('title_index') == '3'
        assert events[3].data.get('title_index') == '6'

    def test_attributes_nonexistent_source(self):
        """Test extracting a custom attribute from a nonexistent source."""
        attributes_definition = [{
            geo_rss_events.CONF_ATTRIBUTES_NAME: 'title_index',
            geo_rss_events.CONF_ATTRIBUTES_SOURCE: 'nonexistent',
            geo_rss_events.CONF_ATTRIBUTES_REGEXP:
                '(?P<' + geo_rss_events.CONF_CUSTOM_ATTRIBUTE + '>\d+)'
        }]
        events = self.prepare_test(attributes_definition=attributes_definition)
        # Check entries
        self.assertEqual(4, len(events))
        assert events[0].data.get('title_index') is ''
        assert events[1].data.get('title_index') is ''
        assert events[2].data.get('title_index') is ''
        assert events[3].data.get('title_index') is ''

    def test_filter(self):
        """Test a custom filter."""
        filters_definition = [{
            geo_rss_events.CONF_FILTERS_ATTRIBUTE: 'title',
            geo_rss_events.CONF_FILTERS_REGEXP:
                'Title [3-9]{1}'
        }]
        events = self.prepare_test(filters_definition=filters_definition)
        # Check entries
        self.assertEqual(2, len(events))
        assert events[0].data.get('title') == 'Title 3'
        assert events[1].data.get('title') == 'Title 6'

    def test_filter_nonexistent_attribute(self):
        """Test a custom filter on non-existent attribute."""
        filters_definition = [{
            geo_rss_events.CONF_FILTERS_ATTRIBUTE: 'nonexistent',
            geo_rss_events.CONF_FILTERS_REGEXP: '.*'
        }]
        events = self.prepare_test(filters_definition=filters_definition)
        # Check entries
        self.assertEqual(4, len(events))
