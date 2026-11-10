package upstream

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

type Result struct {
	Status      int
	Body        []byte
	Header      http.Header
	Err         error
	Unavailable bool
}

type Client struct {
	HTTP    *http.Client
	CoreURL string
	Admin   string
	Actor   string

	mu      sync.Mutex
	video   target
	review  target
	publish target
}

type target struct {
	URL, Token string
}

func New(coreURL, admin, actor string, timeout time.Duration) *Client {
	return &Client{
		HTTP:    &http.Client{Timeout: timeout},
		CoreURL: strings.TrimRight(coreURL, "/"),
		Admin:   admin,
		Actor:   actor,
	}
}

func (c *Client) SetModule(stage, url, token string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	t := target{URL: strings.TrimRight(url, "/"), Token: token}
	switch stage {
	case "video":
		c.video = t
	case "review":
		c.review = t
	case "publish":
		c.publish = t
	}
}

func (c *Client) module(stage string) target {
	c.mu.Lock()
	defer c.mu.Unlock()
	switch stage {
	case "video":
		return c.video
	case "review":
		return c.review
	case "publish":
		return c.publish
	}
	return target{}
}

func (c *Client) DoCore(ctx context.Context, method, path string, body []byte, extra http.Header) Result {
	return c.do(ctx, method, c.CoreURL+path, c.Admin, body, extra, true)
}

func (c *Client) DoModule(ctx context.Context, stage, method, path string, body []byte, extra http.Header) Result {
	t := c.module(stage)
	if t.URL == "" || t.Token == "" {
		return Result{Status: http.StatusServiceUnavailable, Unavailable: true, Err: fmt.Errorf("module %s is not configured", stage)}
	}
	return c.do(ctx, method, t.URL+path, t.Token, body, extra, false)
}

func (c *Client) do(ctx context.Context, method, url, token string, body []byte, extra http.Header, admin bool) Result {
	var rdr io.Reader
	if body != nil {
		rdr = strings.NewReader(string(body))
	}
	req, err := http.NewRequestWithContext(ctx, method, url, rdr)
	if err != nil {
		return Result{Err: err, Unavailable: true}
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Accept", "application/json")
	if admin {
		req.Header.Set("X-Admin-Actor", c.Actor)
	} else {
		req.Header.Set("X-Actor", c.Actor)
		req.Header.Set("X-Admin-Actor", c.Actor)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, vs := range extra {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return Result{Err: err, Unavailable: true}
	}
	defer res.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(res.Body, 2<<20))
	return Result{Status: res.StatusCode, Body: raw, Header: res.Header}
}

// RefreshModules pulls endpoints from core registry; env URLs/tokens win when set.
func (c *Client) RefreshModules(ctx context.Context, envVideo, envReview, envPublish, tokV, tokR, tokP string) error {
	res := c.DoCore(ctx, http.MethodGet, "/internal/v1/modules", nil, nil)
	if res.Err != nil || res.Status >= 300 {
		// still apply env fallbacks
		c.applyEnv(envVideo, envReview, envPublish, tokV, tokR, tokP)
		if res.Err != nil {
			return res.Err
		}
		return fmt.Errorf("core list modules: HTTP %d", res.Status)
	}
	var parsed struct {
		Items []struct {
			ID, StageID, Endpoint string
			// stage field in JSON is StageID
		} `json:"items"`
	}
	_ = json.Unmarshal(res.Body, &parsed)
	// Module JSON uses StageID
	type row struct {
		ID, StageID, Endpoint, Stage string
	}
	var wrap struct {
		Items []map[string]any `json:"items"`
	}
	_ = json.Unmarshal(res.Body, &wrap)
	byStage := map[string]string{}
	for _, m := range wrap.Items {
		stage, _ := m["StageID"].(string)
		if stage == "" {
			stage, _ = m["stage_id"].(string)
		}
		ep, _ := m["Endpoint"].(string)
		if ep == "" {
			ep, _ = m["endpoint"].(string)
		}
		if stage != "" && ep != "" {
			byStage[stage] = ep
		}
	}
	video := first(envVideo, byStage["video"])
	review := first(envReview, byStage["review"])
	publish := first(envPublish, byStage["publish"])
	c.SetModule("video", video, tokV)
	c.SetModule("review", review, tokR)
	c.SetModule("publish", publish, tokP)
	return nil
}

func (c *Client) applyEnv(v, r, p, tv, tr, tp string) {
	if v != "" {
		c.SetModule("video", v, tv)
	}
	if r != "" {
		c.SetModule("review", r, tr)
	}
	if p != "" {
		c.SetModule("publish", p, tp)
	}
}

func first(a, b string) string {
	if a != "" {
		return a
	}
	return b
}
