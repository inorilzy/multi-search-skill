> Source: https://api.stackexchange.com/docs/paging
> Retrieved: 2026-10-31
> Covers: page/pagesize, has_more, total (all methods)

# Paging

## Discussion

    Nearly all methods in the API accept the page and pagesize parameters for fetching specific pages of results from the API.
    page starts at and defaults to 1, pagesize can be any value between 0 and 100 and defaults to 30.

            Since the {ids} and similar parameters on methods like /questions/{ids} are constrained to 100 or fewer ids, it is always possible to fetch the
            entirety of a result from those methods in a single request (the same does not apply to methods like /users/{ids}/answers since the ids passed are not answer ids).  However, it is sometimes more useful to run "top M of N by X" style queries as
            with this most recently active query.

## Fetching All Results

    Oftentimes an application will be interested in fetching all the items that match specific criteria, but this can be complicated when the number of matches
    exceeds 100 (the maximum pagesize).  To assist in this case, the API returns the has_more property on the common wrapper object
    if there are more results to be fetched.  An application can use this property to fetch all results without having to speculatively issue queries or pay for the
    comparatively expensive total property.

## Total

        The total property is available on the common wrapper object (but not returned by default, add it via a filter) for
        cases where the count of items that match a set of constraints is more interesting than the items themselves.
            An example would be the  number of comments in the system to receive any upvotes.

    total is also a useful property when displaying paging controls.  In this case applications would want to include both items and total on
    a filter rather than making two separate requests.

    Fetching total can be equally as expensive as fetching items.  Put another way, an application fetching
    total when not needed is potentially halving its performance.  It is for this reason that total is not returned by default.
