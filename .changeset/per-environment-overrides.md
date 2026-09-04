---
"darth-infra": minor
---

Describe environments that differ in more than their name.

- Add `[environments.<env>.services.<service>]` accepting `cpu`, `memory_mib`, `desired_count`, and `environment_variables`, applied over that service's own values. Scalars replace; `environment_variables` merges key by key, so an environment restates only what actually differs. Covers per-environment values the `{env}` / `{domain}` placeholders cannot derive.
- Add `[environments.<env>.alb]` accepting `shared_alb_name`, `shared_listener_arn`, and `shared_alb_security_group_id`, for projects whose environments live behind different shared load balancers. Resolved at deploy time and never rendered into a template, so all environments still share one set of templates.
- Support the `{project}` and `{env}` placeholders in a secret's `existing_secret_name`, so one `[[secrets]]` entry can name a per-environment Secrets Manager secret. A preview environment resolves `{env}` to its base environment.
- Add `services[].entrypoint`, emitting the container's `EntryPoint` in exec form. Needed when an image's own `ENTRYPOINT` ignores its arguments, which makes a `command` override silently do nothing.
- An explicit `alb.default_listener_priority` now wins over the priority the deployed rule currently holds, so changing it and redeploying moves the live rule. Omitted priorities are still auto-allocated once and then reused, unchanged. This makes a priority change usable to cut traffic over between two stacks sharing one ALB.
