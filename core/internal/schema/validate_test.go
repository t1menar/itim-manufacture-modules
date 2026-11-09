package schema

import (
	"encoding/json"
	"testing"
)

func TestValidateVideoAcceptsStringCover(t *testing.T) {
	raw := []byte(`{
	  "variants": [{
	    "language": "en",
	    "video": {"ref":"s3://x/f.mp4","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","duration_s":1,"size":1,"width":1,"height":1,"fps":1},
	    "contact_sheet": "s3://x/s.jpg",
	    "cover": "s3://x/c.jpg",
	    "post": {"caption":"c","hashtags":["#pg"]},
	    "metadata": {"title":"t","description":"d","topics":["pg"],"platforms":{"instagram":{"caption":"c","hashtags":["#pg"]}}}
	  }],
	  "provenance": {}
	}`)
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	if err := ValidateStageOutput("video", v); err != nil {
		t.Fatal(err)
	}
}

func TestValidateVideoRejectsMissingVariants(t *testing.T) {
	if err := ValidateStageOutput("video", map[string]any{"ok": true}); err == nil {
		t.Fatal("expected error")
	}
}
