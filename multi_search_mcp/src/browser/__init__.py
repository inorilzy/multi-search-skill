"""Browser-backed search/scrape runtime (CloakBrowser).

Optional capability layer: importing this package must not require the
``cloakbrowser`` dependency. Submodules that need the browser import it lazily
so the rest of the MCP keeps working when it is not installed.
"""
