"""Projection sources and the service that scores them; see service.py for the entry point.

Importing the package registers every source, so the API and the worker both see them all."""

from app.services.projections import fantasyiq, sleeper  # noqa: F401  (registers the sources)
