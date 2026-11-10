package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/t1menar/manufacture/admin-api/internal/audit"
	"github.com/t1menar/manufacture/admin-api/internal/bootstrap"
	"github.com/t1menar/manufacture/admin-api/internal/db"
	"github.com/t1menar/manufacture/admin-api/internal/httpapi"
	"github.com/t1menar/manufacture/admin-api/internal/upstream"
)

var version = "dev"

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service", "admin-api", "version", version)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, log); err != nil {
		log.Error("exit", "err", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, log *slog.Logger) error {
	cmd := "serve"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}
	cfg, err := bootstrap.Load(os.Getenv)
	if err != nil {
		return err
	}
	pool, err := db.Open(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool); err != nil {
		return err
	}
	if cmd == "migrate" {
		log.Info("migrations applied")
		return nil
	}
	if cmd != "serve" {
		return fmt.Errorf("unknown command %q (serve, migrate)", cmd)
	}

	up := upstream.New(cfg.CoreURL, cfg.AdminToken, cfg.Actor, cfg.UpstreamTimeout)
	rctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	if err := up.RefreshModules(rctx, cfg.VideoURL, cfg.ReviewURL, cfg.PublishURL, cfg.VideoToken, cfg.ReviewToken, cfg.PublishToken); err != nil {
		log.Warn("module discovery deferred", "err", err)
		up.SetModule("video", cfg.VideoURL, cfg.VideoToken)
		up.SetModule("review", cfg.ReviewURL, cfg.ReviewToken)
		up.SetModule("publish", cfg.PublishURL, cfg.PublishToken)
	}
	cancel()

	aud := &audit.Store{Pool: pool}
	api := &httpapi.Server{
		Cfg: cfg, Up: up, Audit: aud, Log: log,
		Ready: func() error { return pool.Ping(context.Background()) },
	}
	srv := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           api.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
	}
	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()
	log.Info("admin-api started", "addr", cfg.ListenAddr)
	select {
	case <-ctx.Done():
	case err := <-errc:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	}
	sh, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	return srv.Shutdown(sh)
}
