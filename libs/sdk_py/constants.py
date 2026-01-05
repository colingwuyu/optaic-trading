"""Well-known system constants for OptAIC platform.

These constants identify system-level entities that are created during
platform bootstrap. They can be used by SDK clients to reference the
System Space, System Project, and other well-known resources.
"""

from uuid import UUID

# System Tenant - the root tenant for system resources
SYSTEM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

# System Space - contains all system definitions
SYSTEM_SPACE_ID = UUID("00000000-0000-0000-0000-000000000002")

# System Principal - admin account (admin@optaic.local)
SYSTEM_PRINCIPAL_ID = UUID("00000000-0000-0000-0000-000000000003")

# System TenantRoot - root resource for system tenant
SYSTEM_TENANT_ROOT_ID = UUID("00000000-0000-0000-0000-000000000010")

# System Space sub-spaces
SYSTEM_OFFICIAL_SUBSPACE_ID = UUID("00000000-0000-0000-0000-000000000011")
SYSTEM_STAGING_SUBSPACE_ID = UUID("00000000-0000-0000-0000-000000000012")

# System Project - parent for all system definitions
SYSTEM_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000013")
