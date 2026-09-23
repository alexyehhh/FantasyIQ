"""
Business logic layer.

Per AGENTS.md's "single source of business logic" rule: both the REST
API (app/api/v1) and, later, the AI tool layer (app/ai) call into
functions here rather than each implementing their own queries.
"""
