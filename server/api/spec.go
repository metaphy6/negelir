// Package openapi provides the embedded OpenAPI specification for the
// Negelir REST API.  It is the single import point for any Go code that
// needs the raw spec bytes — spec_loader.go (§9.4) validates extensions
// at boot time using EmbeddedSpec.
package openapi

import _ "embed"

// EmbeddedSpec is the canonical server/api/openapi.yaml, compiled into the
// binary at build time so the single-artifact container image carries the
// spec without requiring a sidecar YAML file at runtime.
//
// The authoritative source is server/api/openapi.yaml.  The apigen package
// test (TestOpenAPIRoutesHaveRequiredExtensions) validates the YAML on every
// CI run; boot validation (spec_loader.ValidateSpecExtensions) re-asserts it
// at server startup.
//
//go:embed openapi.yaml
var EmbeddedSpec []byte
