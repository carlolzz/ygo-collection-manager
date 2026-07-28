"""Pricing: providers, the snapshot store, and valuation.

Two rules the whole package exists to enforce:

- Every price read goes through the snapshot store. No provider is ever called
  from a request handler.
- A valuation run picks one source field, and therefore one currency, and
  records which.
"""
