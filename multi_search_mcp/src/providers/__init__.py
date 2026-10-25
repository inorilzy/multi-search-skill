"""Provider-specific helpers shared by both searchers and scrapers.

Modules here may be imported from ``search/`` and ``scrape/`` alike, so this
package must not import either side. ``support/`` holds only provider-agnostic
utilities (secrets, credential store) that these modules build on.
"""
