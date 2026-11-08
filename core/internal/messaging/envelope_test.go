package messaging

import (
	"testing"
	"time"
)

func TestParseRejects(t *testing.T) {
	for name, body := range map[string]string{
		"not json":      `{`,
		"unknown type":  `{"message_id":"01890a5d-ac96-774b-bcce-b302099a8057","type":"x.y","schema_version":1,"producer":"core","payload":{}}`,
		"bad version":   `{"message_id":"01890a5d-ac96-774b-bcce-b302099a8057","type":"job.progress","schema_version":2,"producer":"core","payload":{}}`,
		"job w/o fence": `{"message_id":"01890a5d-ac96-774b-bcce-b302099a8057","type":"job.progress","schema_version":1,"producer":"module:a1","payload":{}}`,
	} {
		if _, err := Parse([]byte(body)); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestBackoffBounded(t *testing.T) {
	if Backoff(0) != time.Second || Backoff(100) != 5*time.Minute {
		t.Fatal(Backoff(1), Backoff(100))
	}
}
