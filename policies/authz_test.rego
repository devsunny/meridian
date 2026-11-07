package edp.authz_test

import rego.v1

import data.edp.authz

analyst := {
	"id": "u_priya",
	"tenant": "acme",
	"project": "finance-analytics",
	"roles": ["Analyst"],
	"mfa": true,
	"grants": [],
}

internal_invoice := {
	"urn": "urn:edp:acme:finance:silver.invoice_lines",
	"tenant": "acme",
	"project": "finance-analytics",
	"classification": "INTERNAL",
	"tags": [],
	"columns": {"invoice_id": {"classification": "INTERNAL", "pii": false}},
}

restricted_customer := {
	"urn": "urn:edp:acme:finance:gold.customer_pii",
	"tenant": "acme",
	"project": "finance-analytics",
	"classification": "RESTRICTED",
	"tags": [],
	"columns": {
		"customer_id": {"classification": "INTERNAL", "pii": false},
		"ssn": {"classification": "RESTRICTED", "pii": true},
	},
}

test_analyst_can_read_internal_in_own_project if {
	authz.allow with input as {
		"principal": analyst,
		"action": "read",
		"resource": internal_invoice,
		"context": {"purpose": "reporting"},
	}
}

test_analyst_cannot_read_other_tenant if {
	not authz.allow with input as {
		"principal": analyst,
		"action": "read",
		"resource": object.union(internal_invoice, {"tenant": "globex"}),
		"context": {"purpose": "reporting"},
	}
}

test_analyst_cannot_read_restricted_without_grant if {
	not authz.allow with input as {
		"principal": analyst,
		"action": "read",
		"resource": restricted_customer,
		"context": {"purpose": "fraud"},
	}
}

test_grant_allows_restricted_with_matching_purpose if {
	authz.allow with input as {
		"principal": object.union(analyst, {
			"grants": [{
				"resource_urn": restricted_customer.urn,
				"action": "read",
				"purpose": "fraud",
				"expires_at_ns": time.now_ns() + 3600000000000,
			}],
		}),
		"action": "read",
		"resource": restricted_customer,
		"context": {"purpose": "fraud"},
	}
}

test_grant_with_wrong_purpose_is_denied if {
	not authz.allow with input as {
		"principal": object.union(analyst, {
			"grants": [{
				"resource_urn": restricted_customer.urn,
				"action": "read",
				"purpose": "fraud",
				"expires_at_ns": time.now_ns() + 3600000000000,
			}],
		}),
		"action": "read",
		"resource": restricted_customer,
		"context": {"purpose": "marketing"},
	}
}

test_expired_grant_is_denied if {
	not authz.allow with input as {
		"principal": object.union(analyst, {
			"grants": [{
				"resource_urn": restricted_customer.urn,
				"action": "read",
				"purpose": "fraud",
				"expires_at_ns": time.now_ns() - 1,
			}],
		}),
		"action": "read",
		"resource": restricted_customer,
		"context": {"purpose": "fraud"},
	}
}

test_restricted_read_produces_column_mask if {
	decision := authz.obligations with input as {
		"principal": analyst,
		"action": "read",
		"resource": restricted_customer,
		"context": {"purpose": "fraud"},
	}
	decision.column_masks.ssn == "sha256"
}

test_training_requires_flag_and_role if {
	not authz.allow with input as {
		"principal": analyst,
		"action": "train",
		"resource": internal_invoice,
		"context": {},
	}
}
