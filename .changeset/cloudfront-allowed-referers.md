---
"darth-infra": minor
---

Limit which sites can use a CloudFront distribution by `Referer`.

- Add `[cloudfront].allowed_referers`, a list of hostnames that each also allow their subdomains. Setting it renders a CloudFront Function on viewer-request for the default and every cached behavior, returning `403` when the `Referer` names any other host. Requests without a `Referer` pass, because browsers omit it for direct navigation and under strict referrer policies.
- The check runs at the edge, so it covers cached responses as well as requests that reach the origin.

Leaving the list empty renders exactly as before.
