package bootstrap

import (
	"fmt"
	"strings"
	"time"
)

type Config struct {
	ListenAddr      string
	DatabaseURL     string
	CoreURL         string
	AdminToken      string // mfa_
	VideoURL        string
	ReviewURL       string
	PublishURL      string
	VideoToken      string // mft_
	ReviewToken     string
	PublishToken    string
	AllowedHosts    []string
	UpstreamTimeout time.Duration
	Actor           string
	UIDir           string
}

func Load(getenv func(string) string) (Config, error) {
	get := func(k, def string) string {
		v := strings.TrimSpace(getenv(k))
		if v == "" {
			return def
		}
		return v
	}
	admin := get("MODULE_CORE_ADMIN_TOKEN", "")
	if admin == "" {
		admin = get("CORE_ADMIN_TOKEN", "")
	}
	if admin == "" {
		return Config{}, fmt.Errorf("MODULE_CORE_ADMIN_TOKEN or CORE_ADMIN_TOKEN is required")
	}
	if !strings.HasPrefix(admin, "mfa_") {
		return Config{}, fmt.Errorf("admin token must use mfa_ prefix")
	}
	dbURL := get("ADMIN_DATABASE_URL", "")
	if dbURL == "" {
		return Config{}, fmt.Errorf("ADMIN_DATABASE_URL is required")
	}
	hosts := splitHosts(get("ADMIN_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]"))
	to := 10 * time.Second
	if s := get("ADMIN_UPSTREAM_TIMEOUT", ""); s != "" {
		d, err := time.ParseDuration(s)
		if err != nil {
			return Config{}, fmt.Errorf("ADMIN_UPSTREAM_TIMEOUT: %w", err)
		}
		to = d
	}
	return Config{
		ListenAddr:      get("ADMIN_LISTEN_ADDR", "127.0.0.1:8080"),
		DatabaseURL:     dbURL,
		CoreURL:         strings.TrimRight(get("CORE_URL", "http://127.0.0.1:58080"), "/"),
		AdminToken:      admin,
		VideoURL:        strings.TrimRight(get("VIDEO_URL", ""), "/"),
		ReviewURL:       strings.TrimRight(get("REVIEW_URL", ""), "/"),
		PublishURL:      strings.TrimRight(get("PUBLISH_URL", ""), "/"),
		VideoToken:      get("MODULE_TOKEN_VIDEO", ""),
		ReviewToken:     get("MODULE_TOKEN_REVIEW", ""),
		PublishToken:    get("MODULE_TOKEN_PUBLISH", ""),
		AllowedHosts:    hosts,
		UpstreamTimeout: to,
		Actor:           get("ADMIN_ACTOR", "local:admin"),
		UIDir:           get("ADMIN_UI_DIR", ""),
	}, nil
}

func splitHosts(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		p = strings.ToLower(strings.TrimSpace(p))
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
