package api

import _ "embed"

// OpenAPIYAML is the admin-api OpenAPI 3.0.3 source.
//
//go:embed openapi.yaml
var OpenAPIYAML []byte
