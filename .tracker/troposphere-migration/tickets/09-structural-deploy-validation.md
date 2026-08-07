# 09 — Structural deploy-time validation

## Parent

Epic: `.tracker/troposphere-migration/` (see `SPEC.md` there and
`docs/adr/0001-troposphere-template-generation.md`).

## What to build

Reimplement the deploy-time safety checks to assert structurally on built
template objects instead of substring-matching rendered text. The function
keeps its role and its failure mode (raise before any AWS call when a
required template element is missing); only the inspection layer changes.
The new implementation consumes `build_project_templates` output directly —
it must not read or parse the YAML files.

## Where to start

- `src/darth_infra/cli/cfn.py:246` — `validate_rendered_deploy_templates`:
  reads `templates/generated/*.yaml` as text and checks markers like
  `"PolicyName: SesSendEmail"`, `"- ses:SendEmail"`, and the RDS env-key
  mapping table (DATABASE_*/POSTGRES_* → host/port/...). Enumerate every
  marker it checks today; each becomes a structural assertion.
- Call sites: `src/darth_infra/cli/deploy_cmd.py:122` and `:177`.
- Tickets 03/05 built the objects being validated (SES policy, RDS secret
  wiring).

## Contract

- Same public behavior: called from the deploy flow after template
  generation, raises with an actionable message naming the service and the
  missing element. Keep raising `FileNotFoundError`-equivalent errors for
  missing templates only if the file-existence check still makes sense at the
  call site — otherwise validate the built mapping (missing service key =
  same error class of failure).
- Every guarantee the text markers provided is preserved as a structural
  assertion (SES policy presence + action list; RDS secret key wiring per
  exposed env var; any others found during enumeration). None are silently
  dropped.
- Until ticket 10 lands, the old text-based function keeps running in the
  shipping deploy path; the structural version lands inert with unit tests.
  (If wired behind the same name, it must not change deploy behavior for the
  Jinja pipeline — safest is a parallel function that ticket 10 swaps in.)

## Out of scope

- No changes to `_build_parameters`, lookups, changeset logic, or any other
  part of `cli/cfn.py`.
- No deletion of the text-based checks (ticket 10 does that at cutover).

## Acceptance criteria

- [x] Unit tests prove the structural validator raises on a template mapping
      missing the SES policy (when config enables it) and on missing RDS
      secret wiring — and passes on correct fixtures from tickets 03/05.
- [x] A checklist in the PR description maps every text marker in the old
      function to its structural assertion.
- [x] Full suite green; shipping deploy path behavior unchanged.

Commands:

```
uv run pytest
uv run pytest tests/ -k "validation"
```

## Text marker → structural assertion checklist

The new `validate_built_deploy_templates` (parallel to the still-shipping
`validate_rendered_deploy_templates`) consumes `build_project_templates`
output and inspects each `Template.to_dict()`. Every old text marker maps to a
structural assertion; none dropped.

| Old text marker (in rendered YAML) | Structural assertion on built objects |
| --- | --- |
| `root.yaml` file exists | `"templates/generated/root.yaml"` key present in the templates mapping (else `FileNotFoundError`) |
| `services/{name}.yaml` file exists | `"templates/generated/services/{name}.yaml"` key present (else `FileNotFoundError`) |
| `PolicyName: SesSendEmail` | `TaskRole` resource has an `iam.Policy` with `PolicyName == "SesSendEmail"` |
| `- ses:SendEmail` | that policy's flattened `Action` set contains `ses:SendEmail` |
| `- ses:SendRawEmail` | that policy's flattened `Action` set contains `ses:SendRawEmail` |
| `- ses:GetSendQuota` | that policy's flattened `Action` set contains `ses:GetSendQuota` |
| RDS env-key mapping table (`DATABASE_*`/`POSTGRES_*` → host/port/dbname/username/password) | expected RDS secret set derived identically; `json_key` resolved via the same `_RDS_SECRET_KEY_BY_ENV` table with `existing_secret_name` fallback |
| `ValueFrom: !Sub '${RdsSecretArn}:{json_key}::'` (rds secret) | container `Secrets` entry with matching `Name` has `ValueFrom == {"Fn::Sub": "${RdsSecretArn}:{json_key}::"}` |
| `- Name: {secret_name}` (rds secret) | `Name` present in the container-definition `Secrets` list |
| `- Name: {secret_name}` (non-rds secret) | `Name` present in the container-definition `Secrets` list |
| `ValueFrom: !Ref {param_name}` (non-rds secret) | that container `Secrets` entry has `ValueFrom == {"Ref": param_name}` |
| `- !Ref {param_name}` (exec-role policy) | `TaskExecutionRole` `ReadSecrets` policy statement `Resource` list contains `{"Ref": param_name}` |
| `{param_name}: !Ref Secret{suffix}` (generate source, root) | some nested-stack `Parameters[param_name] == {"Ref": "Secret{suffix}"}` |
| external secret ARN resolves (`lookups.external_secret_arns[name]` non-empty) | preserved verbatim: raises if the env/existing secret ARN did not resolve |
| `{param_name}: !Ref EnvSecretArn{suffix}` (env/existing source, root) | some nested-stack `Parameters[param_name] == {"Ref": "EnvSecretArn{suffix}"}` |
| `- !Ref {source_name}` for `RdsSecretArn` (exec-role policy) | `TaskExecutionRole` `ReadSecrets` `Resource` list contains `{"Ref": "RdsSecretArn"}` |
| `RdsSecretArn: !Ref RdsCredentialsSecret` (root, when `config.rds`) | some nested-stack `Parameters["RdsSecretArn"] == {"Ref": "RdsCredentialsSecret"}` |

Landing note: the new function is defined in `cli/cfn.py` beside the old one
but is NOT wired into the deploy path — `deploy_cmd.py` still calls
`validate_rendered_deploy_templates`. Ticket 10 performs the swap. Tests in
`tests/test_structural_deploy_validation.py`.

## Blocked by

- 03 (`03-service-stack-core.md`)
- 05 (`05-rds-and-secrets.md`)
