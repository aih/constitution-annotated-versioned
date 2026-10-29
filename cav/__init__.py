"""Versioned static mirror of the Constitution Annotated (constitution.congress.gov)."""

SOURCE_BASE = "https://constitution.congress.gov"
SOURCE_HOST = "constitution.congress.gov"
# Top-level sections whose HTML pages are captured. Other same-host pages are
# linked back to the official site.
PAGE_PREFIXES = ("/browse/", "/resources/")
