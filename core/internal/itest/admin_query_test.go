package itest

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestAdminOverviewProductionsAndCancel(t *testing.T) {
	e := setup(t)
	job, _ := e.startedJob()
	srv := e.apiFull()
	admin := func(method, path string, body string) *http.Response {
		t.Helper()
		var rdr io.Reader
		if body != "" {
			rdr = strings.NewReader(body)
		}
		req, _ := http.NewRequest(method, srv.URL+path, rdr)
		req.Header.Set("Authorization", "Bearer mfa_test_admin_token_xxxxxxxx")
		req.Header.Set("X-Admin-Actor", "local:admin")
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		return res
	}

	res := admin(http.MethodGet, "/internal/v1/modules", "")
	if res.StatusCode != 200 {
		t.Fatalf("list modules: %d %s", res.StatusCode, problemCode(t, res))
	}
	var listed struct {
		Items []struct {
			ID       string `json:"id"`
			Endpoint string `json:"endpoint"`
			Health   string `json:"health"`
			Token    string `json:"token"`
		}
	}
	_ = json.NewDecoder(res.Body).Decode(&listed)
	res.Body.Close()
	if len(listed.Items) < 4 {
		t.Fatalf("want >=4 modules, got %d", len(listed.Items))
	}
	for _, m := range listed.Items {
		if m.Token != "" {
			t.Fatal("list must not include token")
		}
		if m.ID == "vidmod" && m.Endpoint == "" {
			t.Fatal("endpoint missing")
		}
	}

	res = admin(http.MethodGet, "/internal/v1/modules/vidmod", "")
	if res.StatusCode != 200 {
		t.Fatalf("get module: %d", res.StatusCode)
	}
	res.Body.Close()

	res = admin(http.MethodGet, "/internal/v1/overview", "")
	if res.StatusCode != 200 {
		b, _ := io.ReadAll(res.Body)
		t.Fatalf("overview: %d %s", res.StatusCode, b)
	}
	var ov map[string]any
	_ = json.NewDecoder(res.Body).Decode(&ov)
	res.Body.Close()
	if _, ok := ov["jobs"]; !ok {
		t.Fatal("overview missing jobs")
	}

	res = admin(http.MethodGet, "/internal/v1/productions?limit=50", "")
	if res.StatusCode != 200 {
		t.Fatalf("list productions: %d %s", res.StatusCode, problemCode(t, res))
	}
	var plist struct {
		Items []struct{ ID string }
	}
	_ = json.NewDecoder(res.Body).Decode(&plist)
	res.Body.Close()
	if len(plist.Items) < 1 {
		t.Fatal("expected a production from startedJob")
	}
	prodID := plist.Items[0].ID

	res = admin(http.MethodGet, "/internal/v1/productions/"+prodID, "")
	if res.StatusCode != 200 {
		t.Fatalf("get production: %d %s", res.StatusCode, problemCode(t, res))
	}
	var prod struct {
		Jobs   []struct{ ID string }
		Events []struct {
			JobID json.RawMessage `json:"job_id"`
		}
	}
	_ = json.NewDecoder(res.Body).Decode(&prod)
	res.Body.Close()
	if len(prod.Jobs) < 1 {
		t.Fatal("production has no jobs")
	}
	withJob := 0
	for _, ev := range prod.Events {
		if len(ev.JobID) == 0 || string(ev.JobID) == "null" {
			continue
		}
		withJob++
		var s string
		if err := json.Unmarshal(ev.JobID, &s); err != nil {
			t.Fatalf("event job_id must be a uuid string, got %s", ev.JobID)
		}
	}
	if withJob == 0 {
		t.Fatal("expected events with job_id")
	}

	res = admin(http.MethodGet, "/internal/v1/jobs/"+job.String(), "")
	if res.StatusCode != 200 {
		t.Fatalf("get job: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()

	res = admin(http.MethodPost, "/internal/v1/jobs/"+job.String()+"/cancel", `{"reason":"test cancel"}`)
	if res.StatusCode != 204 {
		b, _ := io.ReadAll(res.Body)
		t.Fatalf("cancel: %d %s", res.StatusCode, b)
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'cancelled'`, job); n != 1 {
		t.Fatal("job not cancelled")
	}

	// no token: 401
	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/internal/v1/overview", nil)
	res, _ = http.DefaultClient.Do(req)
	if res.StatusCode != 401 {
		t.Fatalf("unauth overview: %d", res.StatusCode)
	}
	res.Body.Close()
}
