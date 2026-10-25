"""Compatibility alias: Tavily error helpers live in ``providers.tavily``.

``search/`` and ``scrape/`` adapters in this branch still import this path; the
integration step repoints them at ``providers.tavily`` and removes this module.
Re-export the module object itself so a patch on either name affects both.
"""
import sys

from ..providers import tavily as _tavily

sys.modules[__name__] = _tavily
