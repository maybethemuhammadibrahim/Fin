"""[B] The two sources a page can be rendered from. Phase 6.

`demo` returns the mockup's own content; `live` returns whatever the database
holds. Both return the dataclasses in `web.viewmodels`, so the templates are
identical either way and the toggle is a one-word decision made in the router.

They never call each other.
"""

from web.presenters import demo, live

__all__ = ["demo", "live"]
