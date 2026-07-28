"""API-key authentication and the tenant boundary it establishes.

`tenant_id` resolved here is the *only* thing that scopes retrieval (see
`vectorstore/qdrant_store.py::_build_filter`). Nothing in a request body may influence it --
that is the whole point of this package.
"""
