---
"darth-infra": patch
---

Keep Brotli out of the cache policy rendered for `origin_request_headers`.

Legacy forwarded values cannot express Brotli — CloudFront supports it only through a cache policy — so a behavior migrating to a policy has only ever keyed on the Gzip-normalized `Accept-Encoding`. Enabling Brotli alongside it added a cache-key dimension the behavior did not have, which would have split every compressible object already cached under that path and refilled it from the origin.

The rendered cache policy now matches the legacy cache key exactly: the same `Host` and configured query strings and cookies, the same TTLs, Gzip normalization tracking `compress`, and Brotli off. Adding `origin_request_headers` to a live behavior no longer disturbs what it has already cached.
