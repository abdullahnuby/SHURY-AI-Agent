# SHURY Company C6 — Organization Blueprint

This release introduces a single declarative source of truth for the current SHURY Company
organization at `app/organization/organization.toml`.

The runtime loads the catalog through `OrganizationCatalog` and preserves the existing `CEO`, `ROLES`,
and `DEPARTMENTS` public objects for compatibility.

The catalog is intentionally smaller than any external reference organization. SHURY adds a
Department only when a stable responsibility boundary exists.
