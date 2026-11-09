package messaging

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// Conn keeps one AMQP connection open and reconnects with backoff. Readiness uses Check.
type Conn struct {
	URL  string
	Topo Topology
	Log  *slog.Logger
	mu   sync.RWMutex
	conn *amqp.Connection
}

// Current returns the open connection or nil.
func (c *Conn) Current() *amqp.Connection {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.conn == nil || c.conn.IsClosed() {
		return nil
	}
	return c.conn
}

func (c *Conn) Check(context.Context) error {
	if c.Current() == nil {
		return errors.New("broker connection closed")
	}
	return nil
}

func (c *Conn) dial() error {
	conn, err := amqp.DialConfig(c.URL, amqp.Config{Heartbeat: 10 * time.Second, Dial: amqp.DefaultDial(5 * time.Second)})
	if err != nil {
		return err
	}
	ch, err := conn.Channel()
	if err == nil {
		err = c.Topo.DeclareCore(ch)
		_ = ch.Close()
	}
	if err != nil {
		_ = conn.Close()
		return err
	}
	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	return nil
}

// Run maintains the connection until ctx is done.
func (c *Conn) Run(ctx context.Context) {
	attempt := 0
	for ctx.Err() == nil {
		if err := c.dial(); err != nil {
			attempt++
			c.Log.Warn("broker connect failed", "attempt", attempt, "err", err)
			select {
			case <-ctx.Done():
				return
			case <-time.After(min(time.Duration(attempt)*time.Second, 15*time.Second)):
			}
			continue
		}
		attempt = 0
		closed := c.Current().NotifyClose(make(chan *amqp.Error, 1))
		select {
		case <-ctx.Done():
			c.mu.Lock()
			_ = c.conn.Close()
			c.mu.Unlock()
			return
		case err := <-closed:
			c.Log.Warn("broker connection closed; reconnecting", "err", err)
		}
	}
}
