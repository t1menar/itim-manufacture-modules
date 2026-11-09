// Package prompts holds shared helpers for runtime prompt templates.
//
// Storage, activation, audit and per-job snapshots of prompt versions belong to the module
// that runs them (D16 / C40) — for Manufacture that is module-video, not core. Core only
// provides safe placeholder substitution so modules (or ports in other languages) can share
// one substitution contract: {{name}} only, no expressions, no eval.
package prompts

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
)

var (
	// ErrUnknownVar means the template referenced a placeholder absent from the vars map.
	ErrUnknownVar = errors.New("unknown_variable")
	placeholderRE = regexp.MustCompile(`\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}`)
)

// VersionRef is the provenance record a module should attach to its result (C40).
// The module stores immutable versions locally and reports which ones it used.
type VersionRef struct {
	PromptID string `json:"prompt_id"`
	Version  int    `json:"version"`
	SHA256   string `json:"sha256"`
}

// Render substitutes {{var}} placeholders. Unknown variables → ErrUnknownVar.
// Values are inserted literally (no nested expansion, no expression evaluation).
func Render(body string, vars map[string]string) (string, error) {
	var missing []string
	seen := map[string]bool{}
	out := placeholderRE.ReplaceAllStringFunc(body, func(m string) string {
		name := placeholderRE.FindStringSubmatch(m)[1]
		v, ok := vars[name]
		if !ok {
			if !seen[name] {
				seen[name] = true
				missing = append(missing, name)
			}
			return m
		}
		return v
	})
	if len(missing) > 0 {
		sort.Strings(missing)
		return out, fmt.Errorf("%w: %s", ErrUnknownVar, missing[0])
	}
	return out, nil
}

// DeclaredVars returns unique placeholder names in appearance order.
func DeclaredVars(body string) []string {
	seen := map[string]bool{}
	var out []string
	for _, m := range placeholderRE.FindAllStringSubmatch(body, -1) {
		if !seen[m[1]] {
			seen[m[1]] = true
			out = append(out, m[1])
		}
	}
	return out
}
