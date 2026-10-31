> Source: https://api.stackexchange.com/docs/error-handling
> Retrieved: 2026-10-31
> Covers: Error codes and wrapper error_* fields (all methods)

# Error Handling

## Discussion

            There are two classes of errors that can be returned by the API, those encountered during an authentication flow
            and those encountered during a method call.

## Authentication

            Errors generated from the authentication flow are discussed in the authentication documentation and are defined by the
            OAuth 2.0 specification.

## Method Calls

    Errors from method calls are reported on the common response wrapper object in the
    error_id, error_message, and error_name fields.  Note that while it is possible to
    construct a filter that excludes these fields, in the face of an error there is no guarantee that filters will be applied.

    The HTTP code will be 400 (Bad Request) for all errors unless the method was called via JSONP, in which case even an error will be returned as a
    200 (OK).  This is necessary, as a 400 code will generally prevent a client side app from reading the remaining error details if the call was via JSONP.
    In rare cases (typically dealing with network wide maintenance or hardware failure), errors may occur in processing a request before the API determines whether a request is via JSONP; in these cases a 400 (Bad Request) is
    returned.

    Possible errors:

            bad_parameter – 400

            An invalid parameter was passed, this includes even "high level" parameters like key or site.

            access_token_required – 401

            A method that requires an access token (obtained via authentication) was called without one.

            invalid_access_token – 402

            An invalid access token was passed to a method.

            access_denied – 403

            A method which requires certain permissions was called with an access token that lacks those permissions.

            no_method – 404

            An attempt was made to call a method that does not exist.  Note, calling methods that expect numeric ids (like /users/{ids}) with non-numeric ids can also result in this error.

            key_required – 405

            A method was called in a manner that requires an application key (generally, with an access token), but no key was passed.

            access_token_compromised – 406

            An access token is no longer believed to be secure, normally because it was used on a non-HTTPS call.  The access token will be invalidated if this error is returned.

            write_failed – 407

            A write operation was rejected, see the returned error_message for more details.

            duplicate_request – 409

            A request identified by a request_id has already been run.

            internal_error – 500

            An unexpected error occurred in the API and has been logged.

            throttle_violation – 502

            An application has violated part of the rate limiting contract, so the request was terminated.

            temporarily_unavailable – 503

            Some or all of the API is unavailable.  Applications should backoff on requests to the method invoked.

    For testing purposes, the /errors/{id} will simulate any error given its code.  For introspection purposes, the /errors method will return a list of all possible errors the API may return.
