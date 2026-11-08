package messaging

import (
	amqp "github.com/rabbitmq/amqp091-go"
)

// Topology names the exchanges and queues of core-04 §15.2. Prefix isolates test runs.
type Topology struct {
	Prefix        string
	DeliveryLimit int // quorum x-delivery-limit before dead-lettering
}

func (t Topology) Commands() string            { return t.Prefix + "manufacture.commands" }
func (t Topology) Events() string              { return t.Prefix + "manufacture.events" }
func (t Topology) DLX() string                 { return t.Prefix + "manufacture.dlx" }
func (t Topology) CoreEvents() string          { return t.Prefix + "core.job-events" }
func (t Topology) ModuleQueue(m string) string { return t.Prefix + "module." + m + ".commands" }

func (t Topology) limit() int {
	if t.DeliveryLimit > 0 {
		return t.DeliveryLimit
	}
	return 5
}

// DeclareCore declares exchanges, the core events queue and its dead-letter queue.
func (t Topology) DeclareCore(ch *amqp.Channel) error {
	for _, x := range []string{t.Commands(), t.Events(), t.DLX()} {
		if err := ch.ExchangeDeclare(x, "topic", true, false, false, false, nil); err != nil {
			return err
		}
	}
	return t.declareQueue(ch, t.CoreEvents(), t.Events(), "job.#")
}

// DeclareModule declares a module command queue (used by modules and by tests with fake modules).
func (t Topology) DeclareModule(ch *amqp.Channel, moduleID string) error {
	q := t.ModuleQueue(moduleID)
	if err := t.declareQueue(ch, q, t.Commands(), "*.*."+moduleID); err != nil {
		return err
	}
	for _, key := range []string{"notify." + moduleID, "cancel." + moduleID} {
		if err := ch.QueueBind(q, key, t.Commands(), false, nil); err != nil {
			return err
		}
	}
	return nil
}

func (t Topology) declareQueue(ch *amqp.Channel, q, exchange, key string) error {
	dlq := q + ".dlq"
	if _, err := ch.QueueDeclare(dlq, true, false, false, false, amqp.Table{"x-queue-type": "quorum"}); err != nil {
		return err
	}
	if err := ch.QueueBind(dlq, q, t.DLX(), false, nil); err != nil {
		return err
	}
	args := amqp.Table{
		"x-queue-type":              "quorum",
		"x-delivery-limit":          int64(t.limit()),
		"x-dead-letter-exchange":    t.DLX(),
		"x-dead-letter-routing-key": q,
	}
	if _, err := ch.QueueDeclare(q, true, false, false, false, args); err != nil {
		return err
	}
	return ch.QueueBind(q, key, exchange, false, nil)
}
