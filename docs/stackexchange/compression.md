> Source: https://api.stackexchange.com/docs/compression
> Retrieved: 2026-10-31
> Covers: Response compression / Accept-Encoding (all methods)

# Decompressing API Responses

## Discussion

    While our API is HTTP based, we chose to diverge from standard HTTP in one particular area.  During normal operation, we guarantee that all responses are compressed, either with
    GZIP or DEFLATE.  Both of these algorithms are rather old
    and commonplace, most platforms should have built-in tools for handling both and practically all will be able to handle at least GZIP.

## Rationale

    The motivation for this is simple, serving uncompressed content is a loss for all parties.  Bandwidth is, in comparison to CPU time,
    exceptionally expensive and severely limited on many devices.  It's really a no-brainer to require compression accordingly.

    While effectively all browsers will always request compressed content, many (if not all) of the applications using our API will be
    on decidedly less mature HTTP stacks.  The likelihood of many applications not opting into compression, and being materially worse for it, is
    unacceptable.

## Errors

    The API will attempt to preserve the guarantee of compression in the face of errors, however it is possible for errors to occur
    early enough in the stack for compression to not occur.  In these cases, errors will be returned uncompressed.

## History

        There is a way to remain in compliance with the HTTP spec, which is to reject all requests that do not list "gzip" or "deflate" in their Accept-Encoding header.
            Unfortunately, this does not work in practice as far too many proxies (affecting ~1% of users in our experience) will strip out this header.

        We experimented with this approach during the beta period of API version 1.0, and found that it effectively banned a small but non-trivial number of
            potential users.  That many users access the Stack Exchange network from corporate machines exacerbates the problem.

## How to properly consume API responses

    First and foremost, always set the Accept-Encoding header.  Our API will attempt to honor your requested encoding (either GZIP or DEFLATE), falling back to
    GZIP if the header doesn't arrive or is modified en route.

    If Content-Encoding is set on the response, use the specified algorithm.  If it is missing, assume GZIP.

    If response is not compressed this suggests a proxy between the user and us is intentionally decompressing content, or errors are occuring very early
       in processing requests.
       You can detect uncompressed content by checking for the appropriate magic numbers, assuming your library cannot detect this error for you.

    The API will never return an uncompressed response during normal operation.
