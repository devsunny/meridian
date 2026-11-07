# Policy bundle: edp.authz
#
# Decision input (assembled by `govern`):
# {
#   "principal": { "id", "tenant", "roles": [...], "grants": [...], "mfa": bool },
#   "action": "read" | "query" | "export" | "write" | "ingest" | "administer" | "train",
#   "resource": { "urn", "tenant", "project", "classification", "tags": [...],
#                 "columns": { "name": { "classification", "pii" } } },
#   "context": { "purpose", "network", "time" }
# }
#
# Decision output: { "allow": bool, "obligations": {...} }
package edp.authz

import rego.v1

default allow := false

admins := {"PlatformAdmin", "TenantAdmin"}
readers := {"Analyst", "DataEngineer", "Scientist", "DataSteward", "TenantAdmin"}
open_classifications := {"PUBLIC", "INTERNAL"}

# --- Same-tenant, non-restricted reads by role -------------------------------------------
allow if {
	input.action in {"read", "query"}
	some role in input.principal.roles
	role in readers
	input.resource.tenant == input.principal.tenant
	input.resource.classification in open_classifications
	not ("LEGAL_HOLD" in object.get(input.resource, "tags", []))
}

# --- CONFIDENTIAL: requires project membership ------------------------------------------
allow if {
	input.action in {"read", "query"}
	some role in input.principal.roles
	role in readers
	input.resource.tenant == input.principal.tenant
	input.resource.classification == "CONFIDENTIAL"
	input.resource.project == input.principal.project
	not ("LEGAL_HOLD" in object.get(input.resource, "tags", []))
}

# --- RESTRICTED: requires an unexpired, purpose-bound grant -----------------------------
allow if {
	input.action in {"read", "query", "export"}
	some grant in input.principal.grants
	grant.resource_urn == input.resource.urn
	grant.action == input.action
	grant.purpose == input.context.purpose
	time.now_ns() < grant.expires_at_ns
	input.principal.mfa == true
	not ("LEGAL_HOLD" in object.get(input.resource, "tags", []))
}

# --- Administration ----------------------------------------------------------------------
allow if {
	input.action == "administer"
	some role in input.principal.roles
	role in admins
	input.resource.tenant == input.principal.tenant
}

# --- Training is a distinct right, never implied by read --------------------------------
allow if {
	input.action == "train"
	input.resource.tenant == input.principal.tenant
	input.resource.ai_training_allowed == true
	some role in input.principal.roles
	role in {"Scientist", "DataSteward"}
}

# --- Obligations -------------------------------------------------------------------------
# Column masks for PII/RESTRICTED columns unless the principal is a steward.
masks contains column if {
	some column, meta in input.resource.columns
	meta.classification == "RESTRICTED"
	meta.pii == true
	not ("DataSteward" in input.principal.roles)
}

# Row filters are declared on the dataset and narrowed by tenant.
row_filters contains filter if {
	some filter in object.get(input.resource, "row_filters", [])
	filter.tenant == input.principal.tenant
}

obligations := {
	"column_masks": {column: "sha256" | some column in masks},
	"row_filters": [filter | some filter in row_filters],
	"max_rows": 10000,
	"watermark": is_restricted,
} if {
	is_restricted := input.resource.classification == "RESTRICTED"
}
