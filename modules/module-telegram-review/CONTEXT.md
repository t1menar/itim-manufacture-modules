# module-telegram-review: context

- Not a port of `module-review` (legacy job/fence/registration code stays there for reference): a new core around
  `service.ReviewService` with `Bot`/`DecisionSink` Protocols.
- Entry points: `open(OpenRequest)`, `handle(Update)` / `poll_once(offset)`, `redeliver()`, `resend_unsent()`,
  `expire_due()`, `cancel()`, `notify_published()`.
- Card payloads: gate `script` = `{title, hook, takeaway, scenes[{id,title,narration}], post{summary}, cost_usd}`;
  gate `post` = `{title, video{ref,duration_s,size}, cover, post{caption,hashtags}, account, cost_usd}`.
- Routing of a rejected `post` gate belongs to the pipeline (to `scenario` by default), not to this module.
