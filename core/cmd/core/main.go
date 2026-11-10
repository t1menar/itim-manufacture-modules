// Command core runs the Manufacture pipeline engine.
//
//	core serve     (default) migrate, then run HTTP probes, scheduler, outbox relay, event consumer and sweeper
//	core migrate   apply database migrations and exit
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/auth"
	"github.com/t1menar/manufacture/core/internal/bootstrap"
	"github.com/t1menar/manufacture/core/internal/credentials"
	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/httpapi"
	"github.com/t1menar/manufacture/core/internal/messaging"
	"github.com/t1menar/manufacture/core/internal/modules"
	"github.com/t1menar/manufacture/core/internal/publish"
	"github.com/t1menar/manufacture/core/internal/settings"
)

var version = "dev"

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service", "core", "version", version)
	cmd := "serve"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, cmd, log); err != nil {
		log.Error("exit", "err", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, cmd string, log *slog.Logger) error {
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
	switch cmd {
	case "migrate":
		log.Info("migrations applied")
		return nil
	case "serve":
	default:
		return fmt.Errorf("unknown command %q (serve, migrate)", cmd)
	}

	host, _ := os.Hostname()
	topo := messaging.Topology{}
	conn := &messaging.Conn{URL: cfg.AMQPURL, Topo: topo, Log: log}
	store := &settings.Store{Pool: pool}
	master := modules.MasterKey{Version: cfg.MasterKey.Version, Key: cfg.MasterKey.Key}
	reg := &modules.Registry{Pool: pool, Key: master}
	creds := &credentials.Store{Pool: pool, Key: credentials.MasterKey{Version: cfg.MasterKey.Version, Key: cfg.MasterKey.Key}}
	eng := &engine.Engine{Pool: pool, Topo: topo, Log: log, Settings: store}
	pub := &publish.Store{Pool: pool, OnIntentCreated: func(ctx context.Context, tx pgx.Tx, intent publish.Intent) error {
		_, err := eng.CreateRepublishJob(ctx, tx, intent.VariantID, intent.ID, intent.ContentRevisionID, intent.Generation)
		return err
	}}
	eng.Publish = pub
	if u, err := store.CallbackBaseURL(ctx); err == nil {
		eng.CallbackBaseURL = u
	}
	authenticator := &auth.Authenticator{Pool: pool}
	if admin := os.Getenv("CORE_ADMIN_TOKEN"); admin != "" {
		authenticator.AdminTokenHash = auth.HashToken(admin)
	}
	relay := &messaging.Relay{
		Pool: pool, Worker: fmt.Sprintf("%s/%d/relay", host, os.Getpid()), Log: log,
		OnSent: func(ctx context.Context, _ uuid.UUID, body []byte) {
			if err := eng.MarkDispatched(ctx, body); err != nil {
				log.Warn("mark dispatched", "err", err)
			}
		},
	}
	consumer := &messaging.Consumer{Pool: pool, Name: "core.job-events", Queue: topo.CoreEvents(), Handler: eng.HandleEvent, Log: log}

	api := &httpapi.Server{
		Checks: map[string]httpapi.Check{
			"db":     func(c context.Context) error { return pool.Ping(c) },
			"broker": conn.Check,
		},
		Auth: authenticator, Engine: eng, Settings: store, Modules: reg, Credentials: creds, Publish: pub,
	}
	srv := &http.Server{
		Addr: cfg.ListenAddr, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second,
		WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, Handler: api.Handler(),
	}

	var wg sync.WaitGroup
	loops, cancelLoops := context.WithCancel(ctx)
	defer cancelLoops()
	start := func(f func()) { wg.Add(1); go func() { defer wg.Done(); f() }() }
	start(func() { conn.Run(loops) })
	start(func() { relay.Run(loops, conn.Current, time.Second) })
	start(func() {
		for loops.Err() == nil {
			if c := conn.Current(); c != nil {
				if err := consumer.Consume(loops, c); err != nil {
					log.Warn("consumer stopped", "err", err)
				}
			}
			select {
			case <-loops.Done():
			case <-time.After(time.Second):
			}
		}
	})
	// D21: idea intake is via idea.ready consumer (HandleEvent), not a DB poller.
	start(func() {
		t := time.NewTicker(2 * time.Second)
		defer t.Stop()
		for {
			if n, err := eng.SweepTimeouts(loops, 32); err != nil && loops.Err() == nil {
				log.Warn("timeout sweeper", "err", err)
			} else if n > 0 {
				log.Info("timed out jobs", "count", n)
			}
			// B5: ideas parked at the production limit start as soon as a slot frees up.
			if n, err := eng.StartParked(loops); err != nil && loops.Err() == nil {
				log.Warn("parked ideas", "err", err)
			} else if n > 0 {
				log.Info("parked ideas started", "count", n)
			}
			if n, err := eng.DispatchOrphans(loops, 16); err != nil && loops.Err() == nil {
				log.Warn("orphan job dispatcher", "err", err)
			} else if n > 0 {
				log.Info("dispatched queued jobs", "count", n)
			}
			if n, err := reg.MarkOffline(loops, 90*time.Second); err != nil && loops.Err() == nil {
				log.Warn("module offline sweeper", "err", err)
			} else if n > 0 {
				log.Info("modules marked down", "count", n)
			}
			select {
			case <-loops.Done():
				return
			case <-t.C:
			}
		}
	})
	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()
	log.Info("core started", "addr", cfg.ListenAddr)

	select {
	case <-ctx.Done():
	case err := <-errc:
		if !errors.Is(err, http.ErrServerClosed) {
			cancelLoops()
			wg.Wait()
			return err
		}
	}
	log.Info("shutting down")
	shCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_ = srv.Shutdown(shCtx)
	cancelLoops()
	wg.Wait()
	return nil
}
