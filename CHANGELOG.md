# darth-infra

## 0.11.0

### Minor Changes

- [#28](https://github.com/artshumrc/darth-infra-cli/pull/28) [`8245c45`](https://github.com/artshumrc/darth-infra-cli/commit/8245c458561d2283b02e1b3b30a3548120d1f284) Thanks [@d-flood](https://github.com/d-flood)! - Let a cached behavior send a viewer header to the origin without caching on it.

  - Add `origin_request_headers` to `[[cloudfront.cached_behaviors]]`. Legacy forwarded values cannot separate the two concerns — every header they forward also joins the cache key — so a service that wants, say, `Referer` in order to attribute a request to the site that made it had to either fragment its cache one entry per referring domain or go without. Behaviors that set the key now render with a CloudFront cache policy and origin request policy instead: the cache key keeps `Host` (and `Authorization` when `forward_authorization_header` is set) plus the behavior's configured query strings and cookies, while the listed headers reach the origin outside it.
  - The key is rejected for `Host`, which CloudFront always forwards; for `Authorization`, which has its own flag that correctly keeps it in the cache key; and for `Accept-Encoding` while `compress = true`, which CloudFront normalizes itself and ignores in an origin request policy.

  A behavior that leaves `origin_request_headers` empty renders exactly as before, so an unchanged config still deploys as a no-op. Adding the key to a live behavior changes how that behavior's cache key is computed, and its cache refills from the origin once on the next deploy.

## 0.10.0

### Minor Changes

- [#26](https://github.com/artshumrc/darth-infra-cli/pull/26) [`89b7d2d`](https://github.com/artshumrc/darth-infra-cli/commit/89b7d2d1d81b6c2d0e9f1a3ef014d9774254ade2) Thanks [@d-flood](https://github.com/d-flood)! - Make an explicitly configured ALB listener priority safe to rely on.

  - Add `default_listener_priority` to `[environments.<env>.alb]`. Priorities are unique per _listener_, not per project, so environments on different shared listeners that already carry other projects' rules may have no single free priority in common. The project-level value is used when an environment does not set one; both are validated to 1–50000 at load time.
  - A configured priority that is already used by another rule on the resolved listener is now a hard error naming the conflict, instead of being silently replaced with an allocated one. Auto-allocation searches from the bottom of the range, so the old fallback could place a rule _above_ another stack's rule for the same host and take all of its traffic — an outage triggered by a priority typo, invisible until requests moved. A configured priority outside the allowed range fails the same way.

  Omitted priorities are still allocated automatically and then reused across deploys, unchanged.

## 0.9.0

### Minor Changes

- [#25](https://github.com/artshumrc/darth-infra-cli/pull/25) [`c5c21f0`](https://github.com/artshumrc/darth-infra-cli/commit/c5c21f05029e312532b51609d5e74c14f90c21a4) Thanks [@d-flood](https://github.com/d-flood)! - Describe environments that differ in more than their name.

  - Add `[environments.<env>.services.<service>]` accepting `cpu`, `memory_mib`, `desired_count`, and `environment_variables`, applied over that service's own values. Scalars replace; `environment_variables` merges key by key, so an environment restates only what actually differs. Covers per-environment values the `{env}` / `{domain}` placeholders cannot derive.
  - Add `[environments.<env>.alb]` accepting `shared_alb_name`, `shared_listener_arn`, and `shared_alb_security_group_id`, for projects whose environments live behind different shared load balancers. Resolved at deploy time and never rendered into a template, so all environments still share one set of templates.
  - Support the `{project}` and `{env}` placeholders in a secret's `existing_secret_name`, so one `[[secrets]]` entry can name a per-environment Secrets Manager secret. A preview environment resolves `{env}` to its base environment.
  - Add `services[].entrypoint`, emitting the container's `EntryPoint` in exec form. Needed when an image's own `ENTRYPOINT` ignores its arguments, which makes a `command` override silently do nothing.
  - An explicit `alb.default_listener_priority` now wins over the priority the deployed rule currently holds, so changing it and redeploying moves the live rule. Omitted priorities are still auto-allocated once and then reused, unchanged. This makes a priority change usable to cut traffic over between two stacks sharing one ALB.

- [`f485dc7`](https://github.com/artshumrc/darth-infra-cli/commit/f485dc76d028e38ecbabdede64ceb02dbb6462c9) Thanks [@d-flood](https://github.com/d-flood)! - - Add `[rds]` keys `initial_snapshot_identifier` and `initial_snapshot_credentials_secret`, restoring prod from an existing database's snapshot on its first deploy.
  - Read the deployed RDS snapshot identifier and source credentials ARN back from the stack for every environment, not just active previews.
  - Reject configuration keys the schema does not define, suggesting the closest valid name.
  - Print config-file problems as CLI errors instead of tracebacks.
  - Add `darth-infra install-skill`, installing the `darth-infra.toml` authoring skill to `.claude/skills/` and `.agents/skills/`.
  - Install that skill from `darth-infra init`; `--no-skill` skips it.

## 0.8.0

### Minor Changes

- [#22](https://github.com/artshumrc/darth-infra-cli/pull/22) [`48bcde7`](https://github.com/artshumrc/darth-infra-cli/commit/48bcde7f3ac2ef5cd0e2097353921c6e39c28acf) Thanks [@d-flood](https://github.com/d-flood)! - Generate CloudFormation templates from a troposphere object pipeline instead of Jinja text templates. On the next render, files under `templates/generated/` will change formatting (key ordering, quoting, whitespace) — this is a one-time cosmetic diff. Deployed stacks are unaffected: an unchanged `darth-infra.toml` changes no real infrastructure, because every logical ID, parameter, and resource property is preserved exactly. Hand-edited `templates/custom/overrides.yaml` is still never overwritten.

  Note that the deploy's change set is _not_ empty on the cutover. Nested child templates are referenced by content-hashed S3 URLs, and troposphere serializes YAML differently, so every nested `AWS::CloudFormation::Stack` shows as `Modify` with a new `TemplateURL` even when nothing inside it changed. Verify with `darth-infra deploy --env <env> --verify-noop`, which compares leaf resources structurally and ignores that wrapper churn.

  Also fixes a tag regression: dedicated-ALB HTTP/HTTPS listeners are tagged again. troposphere 4.10.2 omits `Tags` from its `Listener` spec, which silently dropped them. Only affects projects using `alb.mode = "dedicated"`.

## 0.7.4

### Patch Changes

- [`ea664c3`](https://github.com/artshumrc/darth-infra-cli/commit/ea664c39c21ede4c9bc4994cc06492e9e802703a) Thanks [@d-flood](https://github.com/d-flood)! - Resolve ALB listener rule priorities dynamically during deploy and allow preview stack retries from CREATE_FAILED.

## 0.7.3

### Patch Changes

- [`dc3d4f5`](https://github.com/artshumrc/darth-infra-cli/commit/dc3d4f5b618d081bda629179ebf2c10a34178b45) Thanks [@d-flood](https://github.com/d-flood)! - implement CLI version floor enforcement

## 0.7.2

### Patch Changes

- [`2cd02da`](https://github.com/artshumrc/darth-infra-cli/commit/2cd02da5d3841532e9e052c336d339a15f181b28) Thanks [@d-flood](https://github.com/d-flood)! - keep rds identifier stable across multiple deploys for same preview

## 0.7.1

### Patch Changes

- [`4011f5e`](https://github.com/artshumrc/darth-infra-cli/commit/4011f5ef898c761c65b992da474cdf0957eec289) Thanks [@d-flood](https://github.com/d-flood)! - add \_retry_aws_call() with backoff, 8 tries

## 0.7.0

### Minor Changes

- [#16](https://github.com/artshumrc/darth-infra-cli/pull/16) [`90e8142`](https://github.com/artshumrc/darth-infra-cli/commit/90e8142bd74c863e9582e617aac68be9f695c3eb) Thanks [@d-flood](https://github.com/d-flood)! - Add initial support for ephemeral preview environments and make the cloud discover DNS namespace project and environment specific

## 0.6.0

### Minor Changes

- [`ec32b0a`](https://github.com/artshumrc/darth-infra-cli/commit/ec32b0a2d1bb0aff4a1880dfd0977e73f3ce523f) Thanks [@d-flood](https://github.com/d-flood)! - Enable arbitrary tags per environment and fix inability to switch screens out of order

## 0.5.0

### Minor Changes

- [`476f774`](https://github.com/artshumrc/darth-infra-cli/commit/476f774cb5dafd71221def0523203e37f60ea4a4) Thanks [@d-flood](https://github.com/d-flood)! - Propogate tags much more thoroughly to more resources, especially ECS tasks

## 0.4.2

### Patch Changes

- [`09a23a4`](https://github.com/artshumrc/darth-infra-cli/commit/09a23a4ba52d96e158e155a5ab2e5e17914b4de7) Thanks [@d-flood](https://github.com/d-flood)! - use ref instead of getatt for referencing existing secrets

## 0.4.1

### Patch Changes

- [`62c041e`](https://github.com/artshumrc/darth-infra-cli/commit/62c041ea8b63d609dfdcff1c1880b8210c6d5ddf) Thanks [@d-flood](https://github.com/d-flood)! - bump

## 0.4.0

### Minor Changes

- [`e6ac91e`](https://github.com/artshumrc/darth-infra-cli/commit/e6ac91e1506e9fd7dcdb43adb6b5b0ad8ea76263) Thanks [@d-flood](https://github.com/d-flood)! - Add ses role permissions

- [`8c40d47`](https://github.com/artshumrc/darth-infra-cli/commit/8c40d47b79550bc17b048ab5b30cf6eaa01c03fc) Thanks [@d-flood](https://github.com/d-flood)! - fail fast on deploy

- [`5f51aa2`](https://github.com/artshumrc/darth-infra-cli/commit/5f51aa25284bb1999c7631b87510bafb4948c60f) Thanks [@d-flood](https://github.com/d-flood)! - Enable adding cloudfront in front of the alb

## 0.3.0

### Minor Changes

- [`60f980f`](https://github.com/artshumrc/darth-infra-cli/commit/60f980fba95701f21f106ef29b3889e044752e72) Thanks [@d-flood](https://github.com/d-flood)! - Major refactor of TUI, additional commands, and ECS fixes

- [`1e83857`](https://github.com/artshumrc/darth-infra-cli/commit/1e83857e873a8fa53332445c103cbaca508d4e2e) Thanks [@d-flood](https://github.com/d-flood)! - Major refactoring and fixing in order to get BTA deployed. Now does s3, cloudfront, rds, secrets, env vars, etc. and add live view output instead of constant streaming

### Patch Changes

- [`002663c`](https://github.com/artshumrc/darth-infra-cli/commit/002663cc3c4e5ff9adf16baa55ae57474403ff83) Thanks [@d-flood](https://github.com/d-flood)! - add container env vars to tui

## 0.2.0

### Minor Changes

- [`7aa89f1`](https://github.com/artshumrc/darth-infra-cli/commit/7aa89f101ab3cc834f77fe1704b793e7bd37232c) Thanks [@d-flood](https://github.com/d-flood)! - add architecture, ulimit config, filesystem typ, etc

## 0.1.0

### Minor Changes

- [`904788a`](https://github.com/artshumrc/darth-infra-cli/commit/904788a4c1ad912868a2036af04405a0afc9e404) Thanks [@d-flood](https://github.com/d-flood)! - Add ec2 launch type, optional service discovery, and fix critical error in environment handling

### Patch Changes

- [`f8fe7e3`](https://github.com/artshumrc/darth-infra-cli/commit/f8fe7e33b986d971ce5165a466233b6d72b4d442) Thanks [@d-flood](https://github.com/d-flood)! - trigger release

## 0.0.4

### Patch Changes

- [`606f6c4`](https://github.com/artshumrc/darth-infra-cli/commit/606f6c4d48645f3c1f945603d431cf5f6e758758) Thanks [@d-flood](https://github.com/d-flood)! - wip ci

## 0.0.3

### Patch Changes

- [`324e207`](https://github.com/artshumrc/darth-infra-cli/commit/324e207f24fcbd04c1da2e6d0f8be0dd9eacebf9) Thanks [@d-flood](https://github.com/d-flood)! - wip ci

## 0.0.2

### Patch Changes

- [`309944b`](https://github.com/artshumrc/darth-infra-cli/commit/309944b01ef284d8d7769342fc953e29b9de94ea) Thanks [@d-flood](https://github.com/d-flood)! - Fix CI

## 0.0.1

### Patch Changes

- [`f0ae919`](https://github.com/artshumrc/darth-infra-cli/commit/f0ae91912e516d233f59436ff6a177dcb4524044) Thanks [@d-flood](https://github.com/d-flood)! - Initial release
