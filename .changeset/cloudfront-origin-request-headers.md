---
"darth-infra": minor
---

Let a cached behavior send a viewer header to the origin without caching on it.

- Add `origin_request_headers` to `[[cloudfront.cached_behaviors]]`. Legacy forwarded values cannot separate the two concerns — every header they forward also joins the cache key — so a service that wants, say, `Referer` in order to attribute a request to the site that made it had to either fragment its cache one entry per referring domain or go without. Behaviors that set the key now render with a CloudFront cache policy and origin request policy instead: the cache key keeps `Host` (and `Authorization` when `forward_authorization_header` is set) plus the behavior's configured query strings and cookies, while the listed headers reach the origin outside it.
- The key is rejected for `Host`, which CloudFront always forwards; for `Authorization`, which has its own flag that correctly keeps it in the cache key; and for `Accept-Encoding` while `compress = true`, which CloudFront normalizes itself and ignores in an origin request policy.

A behavior that leaves `origin_request_headers` empty renders exactly as before, so an unchanged config still deploys as a no-op. Adding the key to a live behavior changes how that behavior's cache key is computed, and its cache refills from the origin once on the next deploy.
