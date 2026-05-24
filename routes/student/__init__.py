"""
Student blueprint package.

The blueprint object is defined in ``_common`` and each sidebar button has
its own module that registers its routes against it.

Layout (one module per sidebar button):
- applications.py  — My applications: dashboard, apply, per-app page, uploads
- announcements.py — Announcements: list + join pay-out
- profile.py       — My profile
"""
from ._common import student_bp, student_required  # re-export for convenience

# Import each module so its @student_bp.route(...) handlers register.
from . import applications   # noqa: F401
from . import announcements  # noqa: F401
from . import profile        # noqa: F401

__all__ = ["student_bp", "student_required"]
