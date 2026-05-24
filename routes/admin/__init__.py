"""
Admin blueprint package.

The blueprint object is defined in ``_common`` and each sidebar button has
its own module that registers its routes against it. Importing the module
here is enough to attach the routes — Flask sees them as soon as the
blueprint is registered on the app.

Layout (one module per sidebar button):
- dashboard.py    — Dashboard: overview stats + analytics charts
- applications.py — Applications: list / review / decisions / docs / packet
- monitoring.py   — Monitoring : verified scholars + pay-out joiners
- users.py        — User management: list / detail / activate / delete
- announcements.py — Announcements: create / list / joiners / delete
- certificates.py — Certificates: pick an event + preview / generate
"""
from ._common import admin_bp, admin_required  # re-export for convenience

# Import each module so its @admin_bp.route(...) handlers register.
from . import dashboard      # noqa: F401
from . import applications   # noqa: F401
from . import monitoring     # noqa: F401
from . import users          # noqa: F401
from . import announcements  # noqa: F401
from . import certificates   # noqa: F401

__all__ = ["admin_bp", "admin_required"]
