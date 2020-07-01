"""Define constants for the NSW Rural Fire Service Feeds integration."""
from datetime import timedelta

DOMAIN = "nsw_rural_fire_service_feed"

PLATFORMS = ("sensor", "geo_location")

FEED = "feed"

CONF_CATEGORIES = "categories"
DEFAULT_RADIUS = 20.0
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

VALID_CATEGORIES = ["Advice", "Emergency Warning", "Not Applicable", "Watch and Act"]
