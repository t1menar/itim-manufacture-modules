package httpapi

import (
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
)

const uiCSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"

func (s *Server) spa(dir string) http.Handler {
	root := filepath.Clean(dir)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			s.notFound(w, r)
			return
		}
		p := r.URL.Path
		if p == "" || strings.HasPrefix(p, "/api/") || p == "/health" || p == "/ready" {
			s.notFound(w, r)
			return
		}
		rel := path.Clean("/" + p)
		if strings.Contains(rel, "..") {
			s.notFound(w, r)
			return
		}
		full := filepath.Join(root, filepath.FromSlash(rel))
		if !isUnder(root, full) {
			s.notFound(w, r)
			return
		}
		st, err := os.Stat(full)
		if err == nil && !st.IsDir() {
			setUIHeaders(w, rel)
			http.ServeFile(w, r, full)
			return
		}
		// SPA fallback for extension-less paths; unknown static files stay 404.
		if path.Ext(rel) != "" && rel != "/index.html" {
			s.notFound(w, r)
			return
		}
		index := filepath.Join(root, "index.html")
		if _, err := os.Stat(index); err != nil {
			s.notFound(w, r)
			return
		}
		setUIHeaders(w, "/index.html")
		http.ServeFile(w, r, index)
	})
}

func setUIHeaders(w http.ResponseWriter, rel string) {
	w.Header().Set("Content-Security-Policy", uiCSP)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	if strings.HasPrefix(rel, "/assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
		return
	}
	w.Header().Set("Cache-Control", "no-cache")
}

func isUnder(root, full string) bool {
	rel, err := filepath.Rel(root, full)
	if err != nil {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}
