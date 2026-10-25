"""Compatibility alias: the X cookie helpers live in ``providers.xkit``.

``search/`` and ``scrape/`` adapters in this branch still import this path; the
integration step repoints them at ``providers.xkit`` and removes this module.
Re-export the module object itself so a patch on either name affects both.
"""
import sys

from ..providers import xkit as _xkit

sys.modules[__name__] = _xkit
