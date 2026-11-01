> Source: https://api.stackexchange.com/docs/throttle
> Retrieved: 2026-10-31
> Covers: Rate limits, daily quota, backoff (all methods)

Throttles  -
        Stack Exchange API

    -

# Throttles

## Discussion

    In order to prevent abuse the API implements a number of throttles.

    Every application is subject to an IP based concurrent request throttle.  If a single IP is making more than 30 requests a second, new requests will
    be dropped.  The exact ban period is subject to change, but will be on the order of 30 seconds to a few minutes typically.  Note that
    exactly what response an application gets (in terms of HTTP code, text, and so on) is undefined when subject to this ban; we consider > 30 request/sec per IP
    to be very abusive and thus cut the requests off very harshly.

    After that, applications are sorted into two distinct throttles.  Those with, and those without, valid access_tokens (obtained via authenticating a user).

    If an application does not have an access_token, then the application shares an IP based quota with all other applications on that IP.
    This quota is based on the key being passed by the applications; it is the max of the daily request limit for the applications involved,
    which by default is 10,000.  This quota scheme is essentially unchanged from earlier versions of the API.

    If an application does have an access_token, then the application is on a distinct user/app pair daily quota (default size of 10,000).
    A user can have up to 5 distinct quotas at any one time, though this limit is not reflected in quota_remaining returns for privacy reasons.

    A dynamic throttle is also in place on a per-method level.  If an application receives a response with the backoff field set, it must
    wait that many seconds before hitting the same method again.  For the purposes of throttling, all /me routes are considered to be identical to their
    /users/{ids} equivalent.  Note that backoff is set based on a combination of factors, and may not be consistently returned for the same
    arguments to the same method.  Additionally, all methods (even seemingly trivial ones) may return backoff.

    While not strictly a throttle, the API employs heavy caching and as such no application should make semantically identical requests more
        than once a minute. This is generally a waste of bandwidth as, more often than not, the exact same result will be returned.
