> Source: https://api.stackexchange.com/docs/wrapper
> Retrieved: 2026-10-31
> Covers: Common response wrapper (items, backoff, quota_*, has_more)

# Common Wrapper Object

## Discussion

    All responses in the API share a common format, so as to make parsing these responses simpler.

    The error_* fields, while technically eligible for filtering, will not actually be excluded in an
    error case.  This is by design.

    page and page_size are whatever was passed into the method.

    If you're looking to just select total, exclude the items field in favor of excluding all
    the properties on the returned type.

    When building filters, this common wrapper object has no name.  Refer to it with a leading ., so the items
    field would be referred to via .items.

    The backoff field is only set when the API detects the request took an unusually long time to run.  When it is set
    an application must wait that number of seconds before calling that method again.
        Note that for the purposes of throttling and backoff, the /me routes are considered the same as their /users/{ids} equivalent.

## Fields

            backoff

            integer

                    may be absent

            error_id

            integer, refers to an error

                    may be absent

            error_message

            string

                    may be absent

            error_name

            string

                    may be absent

            has_more

            boolean

            items

            an array of the type found in type

            page

            integer

            page_size

            integer

            quota_max

            integer

            quota_remaining

            integer

            total

            integer

            type

            string

    Fields marked with  are included in the default filter, those marked with
     are excluded in the default filter.
