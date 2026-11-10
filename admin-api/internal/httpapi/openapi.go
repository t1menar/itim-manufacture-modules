package httpapi

import (
	"encoding/json"
	"fmt"
	"sync"

	"gopkg.in/yaml.v3"

	"github.com/t1menar/manufacture/admin-api/api"
)

var (
	openapiOnce sync.Once
	openapiJSON []byte
	openapiErr  error
)

// OpenAPIJSON returns the OpenAPI document as JSON (from the embedded YAML).
func OpenAPIJSON() ([]byte, error) {
	openapiOnce.Do(func() {
		var doc any
		if err := yaml.Unmarshal(api.OpenAPIYAML, &doc); err != nil {
			openapiErr = fmt.Errorf("parse openapi.yaml: %w", err)
			return
		}
		b, err := json.Marshal(doc)
		if err != nil {
			openapiErr = err
			return
		}
		openapiJSON = b
	})
	return openapiJSON, openapiErr
}
