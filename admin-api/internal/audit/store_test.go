package audit

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestMaskRedactsSecretKeysAndLeavesOthers(t *testing.T) {
	in := map[string]any{
		"actor":        "local:admin",
		"key":          "telegram.bot_token",
		"value":        "dummy-telegram-bot-token-not-real",
		"access_token": "dummy-ig-token-not-a-real-secret",
		"note":         "ok",
	}
	out, ok := mask(in).(map[string]any)
	if !ok {
		t.Fatalf("mask type %T", mask(in))
	}
	if out["value"] != "***" || out["access_token"] != "***" || out["key"] != "***" {
		t.Fatalf("expected secret keys masked, got %#v", out)
	}
	if out["actor"] != "local:admin" || out["note"] != "ok" {
		t.Fatalf("non-secret fields changed: %#v", out)
	}
	raw, _ := json.Marshal(out)
	if strings.Contains(string(raw), "dummy-") {
		t.Fatalf("dummy secret leaked after mask: %s", raw)
	}
}
