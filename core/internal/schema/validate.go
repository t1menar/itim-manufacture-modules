// Package schema validates stage result outputs against the JSON Schemas in core/schemas.
package schema

import (
	"embed"
	"fmt"
	"io/fs"
	"strings"
	"sync"

	"github.com/santhosh-tekuri/jsonschema/v5"
)

//go:embed schemas/*.json
var schemaFS embed.FS

var (
	once    sync.Once
	loaded  map[string]*jsonschema.Schema
	loadErr error
)

// stageFiles maps pipeline stage_id → schema file under the embedded schemas/ dir.
var stageFiles = map[string]string{
	"video":   "stage-video-output.json",
	"review":  "stage-review-output.json",
	"publish": "stage-publish-output.json",
}

func load() {
	once.Do(func() {
		loaded = map[string]*jsonschema.Schema{}
		c := jsonschema.NewCompiler()
		c.Draft = jsonschema.Draft2020
		entries, err := fs.ReadDir(schemaFS, "schemas")
		if err != nil {
			loadErr = err
			return
		}
		for _, e := range entries {
			if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
				continue
			}
			name := e.Name()
			f, err := schemaFS.Open("schemas/" + name)
			if err != nil {
				loadErr = err
				return
			}
			if err := c.AddResource("https://manufacture.local/schemas/"+name, f); err != nil {
				_ = f.Close()
				loadErr = fmt.Errorf("%s: %w", name, err)
				return
			}
			_ = f.Close()
		}
		for stage, file := range stageFiles {
			s, err := c.Compile("https://manufacture.local/schemas/" + file)
			if err != nil {
				loadErr = fmt.Errorf("compile %s: %w", file, err)
				return
			}
			loaded[stage] = s
		}
	})
}

// ValidateStageOutput checks output against the stage schema. Unknown stages are skipped (nil).
// Returns a non-nil error when validation fails.
func ValidateStageOutput(stageID string, output any) error {
	load()
	if loadErr != nil {
		return loadErr
	}
	s := loaded[stageID]
	if s == nil {
		return nil
	}
	if err := s.Validate(output); err != nil {
		return err
	}
	return nil
}
