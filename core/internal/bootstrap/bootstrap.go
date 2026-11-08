// Package bootstrap reads the only environment variables core uses (core-03 §4.1, plus
// CORE_AMQP_URL for the broker, D11). Everything else is a core setting in the database.
package bootstrap

import (
	"encoding/base64"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

type Config struct {
	DatabaseURL string
	ListenAddr  string
	AMQPURL     string
	MasterKey   MasterKey
}

// MasterKey is the versioned AES-256 key; it is validated here and used by the credentials slice later.
type MasterKey struct {
	Version int
	Key     []byte
}

// String never reveals the key.
func (k MasterKey) String() string { return fmt.Sprintf("master-key(v%d)", k.Version) }

// Load reads configuration through getenv so tests do not touch the process environment.
func Load(getenv func(string) string) (Config, error) {
	var errs []error
	req := func(name string) string {
		v := strings.TrimSpace(getenv(name))
		if v == "" {
			errs = append(errs, fmt.Errorf("%s is required", name))
		}
		return v
	}
	c := Config{
		DatabaseURL: req("CORE_DATABASE_URL"),
		ListenAddr:  req("CORE_LISTEN_ADDR"),
		AMQPURL:     req("CORE_AMQP_URL"),
	}
	if raw := req("CORE_MASTER_KEY"); raw != "" {
		k, err := ParseMasterKey(raw)
		if err != nil {
			errs = append(errs, err)
		}
		c.MasterKey = k
	}
	return c, errors.Join(errs...)
}

// ParseMasterKey parses "<version>:<base64 of 32 bytes>".
func ParseMasterKey(raw string) (MasterKey, error) {
	v, b64, ok := strings.Cut(raw, ":")
	if !ok {
		return MasterKey{}, errors.New("CORE_MASTER_KEY must be <version>:<base64 of 32 bytes>")
	}
	ver, err := strconv.Atoi(v)
	if err != nil || ver < 0 {
		return MasterKey{}, errors.New("CORE_MASTER_KEY version must be a non-negative integer")
	}
	key, err := base64.StdEncoding.DecodeString(b64)
	if err != nil || len(key) != 32 {
		return MasterKey{}, errors.New("CORE_MASTER_KEY must decode to exactly 32 bytes")
	}
	return MasterKey{Version: ver, Key: key}, nil
}
