package bootstrap

import (
	"strings"
	"testing"
)

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

const devKey = "1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" // 32 zero bytes, obviously fake

func TestLoad(t *testing.T) {
	ok := map[string]string{"CORE_DATABASE_URL": "postgres://x", "CORE_LISTEN_ADDR": ":8080", "CORE_AMQP_URL": "amqp://x", "CORE_MASTER_KEY": devKey}
	c, err := Load(env(ok))
	if err != nil {
		t.Fatal(err)
	}
	if c.MasterKey.Version != 1 || len(c.MasterKey.Key) != 32 {
		t.Fatalf("bad key %v", c.MasterKey)
	}
	if strings.Contains(c.MasterKey.String(), "AAAA") {
		t.Fatal("key leaked by String")
	}
	tests := map[string]map[string]string{
		"missing all": {},
		"bad key":     {"CORE_DATABASE_URL": "x", "CORE_LISTEN_ADDR": "x", "CORE_AMQP_URL": "x", "CORE_MASTER_KEY": "1:c2hvcnQ="},
		"no version":  {"CORE_DATABASE_URL": "x", "CORE_LISTEN_ADDR": "x", "CORE_AMQP_URL": "x", "CORE_MASTER_KEY": "AAAA"},
	}
	for name, m := range tests {
		if _, err := Load(env(m)); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
}
