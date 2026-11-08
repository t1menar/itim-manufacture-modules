// Command core runs the Manufacture pipeline engine.
//
//	core serve     (default) migrate, then run HTTP probes, scheduler, outbox relay and event consumer
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

	"github.com/t1menar/manufacture/core/internal/bootstrap"
	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/httpapi"
	"github.com/t1menar/manufacture/core/internal/messaging"
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
	eng := &engine.Engine{Pool: pool, Topo: topo, Log: log}
	relay := &messaging.Relay{Pool: pool, Worker: fmt.Sprintf("%s/%d/relay", host, os.Getpid()), Log: log}
	consumer := &messaging.Consumer{Pool: pool, Name: "core.job-events", Queue: topo.CoreEvents(), Handler: eng.HandleJobEvent, Log: log}

	srv := &http.Server{Addr: cfg.ListenAddr, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second,
		Handler: (&httpapi.Server{Checks: map[string]httpapi.Check{"db": func(c context.Context) error { return pool.Ping(c) }, "broker": conn.Check}}).Handler()}

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
	start(func() {
		t := time.NewTicker(5 * time.Second)
		defer t.Stop()
		for {
			if _, err := eng.Tick(loops); err != nil && loops.Err() == nil {
				log.Warn("scheduler tick", "err", err)
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
