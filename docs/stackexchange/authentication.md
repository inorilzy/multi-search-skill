> Source: https://api.stackexchange.com/docs/authentication
> Retrieved: 2026-10-31
> Covers: Auth / API key header (all methods)

# Authentication

## Discussion

        The Stack Exchange API offers user authentication via OAuth 2.0, specifically templated after Facebook's implementation.
        There are two flows, an authorization grant for server side applications and an implicit one for pure browser based ones.

        For the current details about authentication (as of June 2025) please visit the API authentication help center page.

        The OAuth 2.0 authorization grant consists of the following steps:

                Send a user to https://stackoverflow.com/oauth, with these query string parameters

                        client_id

                        scope (details)

                        redirect_uri - must be under an apps registered domain

                        state - optional

                The user approves your app

                The user is redirected to redirect_uri, with these query string parameters

                        code

                        state - optional, only returned if provided in the first step

                POST (application/x-www-form-urlencoded) the following parameters to https://stackoverflow.com/oauth/access_token

                        client_id

                        client_secret

                        code - from the previous step

                        redirect_uri - must be the same as the provided in the first step

                    This request is responded to with either an error (HTTP status code 400) or an access token of the form access_token=...&expires=1234.
                    expires will only be set if scope does not include no_expiry, the use of which is strongly advised against unless your
                    app truly needs perpetual access.

                    In order to get access_token and expires (if applicable) wrapped in a JSON object,
                       POST to https://stackoverflow.com/oauth/access_token/json instead.

        The implicit OAuth 2.0 flow consists of the following steps:

                Open a new window at https://stackoverflow.com/oauth/dialog, with these query string parameters

                        client_id

                        scope (details)

                        redirect_uri - must be under an apps registered domain

                        state - optional

                The user approves your app

                The user is redirected to redirect_uri, with these parameters in the hash

                        access_token

                        expires - optional, only if scope doesn't contain no_expiry

        The authorization grant should be used by server-side applications, with special care taken to never leak client_secret.
        Client side applications should use the implicit flow.

        After you have authenticated a user once, regardless of flow, subsequent re-authorizations will occur without requiring user action.
        Naturally, should a user revoke an applications permissions then further action will be required to re-authorize.

        Applications using the implicit flow can make use of our provided minimalistic JavaScript SDK.

## Scope

            With an empty scope, authentication will only allow an application to identify a user via the /me method.
            In order to access other information, different scope values must be sent.  Multiple values may be sent in scope by
            comma or space delimitting them.

                read_inbox - access a user's global inbox

                no_expiry - access_token's with this scope do not expire

                write_access - perform write operations as a user 2.1

                private_info - access full history of a user's private actions on the site 2.1

## Desktop Applications

        Desktop applications cannot participate directly in OAuth 2.0 flows, however the embeddable browser controls available in most frameworks
        make it possible to work around this limitation.

        Desktop applications should use the implicit client-side flow, hosting the process within a browser control.  For redirect_uri, a value of
        https://stackoverflow.com/oauth/login_success should be used.  Upon a successful authentication, access_token will
        be placed in the url hash as with a standard implicit authentication.

        If you don't own a domain, or are creating a non-web application, you can still use the OAuth Implicit grant type with
        www.stackexchange.com/oauth/login_success as your redirect URI. To do this, click Manage OAuth in Stack Apps.
        Enable Non-Web Redirect URL and Implicit. Follow the instructions above to configure OAuth implicit grant.

## Usage

            All API requests must pass authentication details using request headers. Your application's API key or access token must be provided using the authorization header Authorization: Bearer {API key or access token}.

## Errors

        OAuth 2.0 reports redirection errors in one of two ways: displaying an error page to the user, or redirecting to an application with the error and error_description parameters.
        Which of these two occurs depends on what the exact error is.  Any error that cast doubt on the application (for example, an unknown client_id) causes the first case, all others cause the later case.
        Note that the user rejecting an application is conceptually an error.

        Possible errors are:

                invalid_request

                unauthorized_client

                access_denied

                unsupported_response_type

                invalid_scope

                server_error

                temporarily_unavailable

        For the authorization grant, calls to /oauth/access_token will respond with the same error codes, wrapped in a JSON object of the form

        { "error": { "type": "invalid_request", "message": "some reason" } }

        Note that there is no guarantee that message will be set.

## Authenticating Applications

        Some applications need the separate request quotas associated with authenticated users without actually having a notion of "users" to authenticate.
        This is most common on shared hosting solutions, such as Google App Engine, where many applications may share a single IP address.

        Rather than using a separate authentication path for applications, an author of such an application should obtain (via a normal OAuth 2.0 flow) a no_expiry token
        under their own account for the exclusive use of their application.

## Unregistered Users

        The Stack Exchange sites make it easy for users to participate without registering, however to authenticate with the API a user must
        be registered.  This is driven by both technical concerns and philosophical ones.

        Technically, there's no easy way to identify unregistered users while operating under the stackexchange.com domain.  The most obvious work around,
        making authentication site-centric instead of network wide, would solve this it would make user's with accounts on multiple sites experience much
        worse.  Other approaches, in the vein of global login, are rather brittle
        and difficult to guarantee will work with all auth flows.

        Philosophically, there are methods which we want to provide to clients but also want to watch for abuse.  In version 2.0, the /events
        method is an example.  We want to provide this data, but we also want to be able to shut down scrapers who aren't following our attribution terms.  Forcing
        abusive users to register to, well, abuse makes it easier to deal with them.  It's easy to envision bits of the write API that will need similar protection.
