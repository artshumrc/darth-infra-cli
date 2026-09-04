---
"darth-infra": minor
---

Make an explicitly configured ALB listener priority safe to rely on.

- Add `default_listener_priority` to `[environments.<env>.alb]`. Priorities are unique per *listener*, not per project, so environments on different shared listeners that already carry other projects' rules may have no single free priority in common. The project-level value is used when an environment does not set one; both are validated to 1–50000 at load time.
- A configured priority that is already used by another rule on the resolved listener is now a hard error naming the conflict, instead of being silently replaced with an allocated one. Auto-allocation searches from the bottom of the range, so the old fallback could place a rule *above* another stack's rule for the same host and take all of its traffic — an outage triggered by a priority typo, invisible until requests moved. A configured priority outside the allowed range fails the same way.

Omitted priorities are still allocated automatically and then reused across deploys, unchanged.
