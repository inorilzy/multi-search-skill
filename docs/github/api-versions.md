> Source: https://docs.github.com/api/article/body?pathname=/en/rest/about-the-rest-api/api-versions
> Retrieved: 2026-10-31
> Covers: X-GitHub-Api-Version header, supported versions (2026-03-10, 2022-11-28)

# API Versions

Learn how to specify which REST API version to use whenever you make a request to the REST API.

## About API versioning

The GitHub REST API is versioned. The API version name is based on the date when the API version was released. For example, the API version `2026-03-10` was released on Tue, 10 Mar 2026.

Breaking changes are changes that can potentially break an integration. Breaking changes will be released in a new API version. We will provide advance notice before releasing breaking changes. Breaking changes include:

* Removing an entire operation
* Removing or renaming a parameter
* Removing or renaming a response field
* Adding a new required parameter
* Making a previously optional parameter required
* Changing the type of a parameter or response field
* Removing enum values
* Adding a new validation rule to an existing parameter
* Changing authentication or authorization requirements

Any additive (non-breaking) changes will be available in all supported API versions. Additive changes are changes that should not break an integration. Additive changes include:

* Adding an operation
* Adding an optional parameter
* Adding an optional request header
* Adding a response field
* Adding a response header
* Adding enum values

When a new REST API version is released, the previous API version will be supported for at least 24 more months following the release of the new API version.

## Specifying an API version

You should use the `X-GitHub-Api-Version` header to specify an API version. For example:

```shell
curl --header "X-GitHub-Api-Version:2026-03-10" https://api.github.com/zen
```

Requests without the `X-GitHub-Api-Version` header will default to use the `2022-11-28` version.

If you specify an API version that is no longer supported, you will receive a `410 Gone` response.

## Upgrading to a new API version

Before upgrading to a new REST API version, you should read the changelog of breaking changes for the new API version to understand what breaking changes are included and to learn more about how to upgrade to that specific API version. For more information, see [Breaking changes](/en/rest/about-the-rest-api/breaking-changes).

When you update your integration to specify the new API version in the `X-GitHub-Api-Version` header, you'll also need to make any changes required for your integration to work with the new API version.

Once your integration is updated, test your integration to verify that it works with the new API version.

## API version closing down

API versions are supported for 24 months after a newer API version is released.

While a version is within its support window but approaching  closing down, GitHub includes the following headers in API responses to help you prepare for migration:

* `Deprecation` — The date when the API version will be closing down, formatted as an HTTP date per [RFC 7231](https://tools.ietf.org/html/rfc7231#section-7.1.1.1). For example: `Wed, 27 Nov 2019 14:34:29 GMT`. <!-- markdownlint-disable-line GHD046 -->
* `Sunset` — The date when the API version will be completely removed (retired), after which requests will return a `410 Gone` response. Follows [RFC 8594](https://tools.ietf.org/html/rfc8594). For example: `Fri, 27 Nov 2020 14:34:29 GMT`. <!-- markdownlint-disable-line GHD046 -->

After the support window ends:

* Requests that specify a closing down API version receive a `410 Gone` response.
* Requests that do not specify an API version default to the next oldest supported version, not the closing down version. If you rely on unversioned requests, you may observe behavioral changes as older versions are removed from support.

For more information on migrating to a newer API version, see [Breaking changes](/en/rest/about-the-rest-api/breaking-changes).

## Exceptions to standard versioning

In rare cases, GitHub may make changes outside the normal API versioning cadence. These are exceptional interventions that do not alter the standard versioning guarantees for most integrators.

### Security, availability, and reliability issues

Critical security vulnerabilities, data exposure risks, or severe reliability issues may require changes outside the normal release schedule. GitHub may release an unscheduled API version, backport fixes to supported versions, or in rare cases, introduce a breaking change to an existing version to protect users and platform integrity.

GitHub will communicate such changes through release notes, changelogs, and direct communication explaining what changed and why. Where feasible, advance notice will be provided. Immediate action may be taken without advance notice when required.

### Low-usage services

For certain services with very low usage, GitHub may deprecate functionality outside the standard versioning process. In these cases, GitHub will communicate the intent and reach out to affected integrators directly.

## Supported API versions

The following REST API versions are currently supported.

| API version  | End of support date |
| ------------ | ------------------- |
| `2026-03-10` | Not yet scheduled   |
| `2022-11-28` | March 10, 2028      |

You can also make an API request to get all of the supported API versions. For more information, see [REST API endpoints for meta data](/en/rest/meta/meta#get-all-api-versions).