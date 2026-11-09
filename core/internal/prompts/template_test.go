package prompts

import (
	"errors"
	"strings"
	"testing"
)

func TestRenderOK(t *testing.T) {
	out, err := Render("Hello {{name}}, id={{id}}", map[string]string{"name": "Tim", "id": "42"})
	if err != nil || out != "Hello Tim, id=42" {
		t.Fatalf("%q %v", out, err)
	}
}

func TestRenderUnknownVar(t *testing.T) {
	_, err := Render("Hello {{name}}", map[string]string{})
	if !errors.Is(err, ErrUnknownVar) {
		t.Fatalf("%v", err)
	}
}

func TestRenderNoEvalOrInjection(t *testing.T) {
	// Values are literal; nested placeholders in values are not expanded; no code runs.
	out, err := Render("x={{a}}", map[string]string{"a": "{{b}}"})
	if err != nil || out != "x={{b}}" {
		t.Fatalf("%q %v", out, err)
	}
	evil := map[string]string{"x": "'); DROP TABLE prompts;--"}
	out, err = Render("{{x}}", evil)
	if err != nil || out != evil["x"] {
		t.Fatalf("value not literal: %q", out)
	}
	if strings.Contains(out, "DROP") && out != evil["x"] {
		t.Fatal("unexpected")
	}
}

func TestDeclaredVars(t *testing.T) {
	got := DeclaredVars("{{a}} and {{b}} and {{a}}")
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Fatal(got)
	}
}
