> Source: https://docs.github.com/api/article/body?pathname=/en/rest/search/search
> Retrieved: 2026-10-31
> Covers: GET /search/repositories (used), plus all other /search/* endpoints, search rate limits, query limits, incomplete_results

# REST API endpoints for search

Use the REST API to search for specific items on GitHub.

## About search

You can use the REST API to search for the specific item you want to find. For example, you can find a user or a specific file in a repository. Think of it the way you think of performing a search on Google. It's designed to help you find the one result you're looking for (or maybe the few results you're looking for). Just like searching on Google, you sometimes want to see a few pages of search results so that you can find the item that best meets your needs. To satisfy that need, the GitHub REST API provides **up to 1,000 results for each search**.

You can narrow your search using queries. To learn more about the search query syntax, see [REST API endpoints for search](/en/rest/search/search#constructing-a-search-query).

### Ranking search results

Unless another sort option is provided as a query parameter, results are sorted by best match in descending order. Multiple factors are combined to boost the most relevant item to the top of the result list.

### Rate limit

The REST API has a custom rate limit for searching. For authenticated requests, you can make up to
30 requests per minute for all search endpoints except for the [Search code](/en/rest/search/search#search-code) endpoint. The [Search code](/en/rest/search/search#search-code) endpoint requires you to authenticate and limits you to 10 requests per minute. For unauthenticated requests, the rate limit allows you to make up to 10 requests per minute.

For information about how to determine your current rate limit status, see [Rate Limit](/en/rest/rate-limit/rate-limit).

### Constructing a search query

Each endpoint for searching uses [query parameters](https://en.wikipedia.org/wiki/Query_string) to perform searches on GitHub. See the individual endpoints for examples that include the endpoint and query parameters.

A query can contain any combination of search qualifiers supported on GitHub. The format of the search query is:

```text
SEARCH_KEYWORD_1 SEARCH_KEYWORD_N QUALIFIER_1 QUALIFIER_N
```

For example, if you wanted to search for all *repositories* owned by `defunkt` that
contained the word `GitHub` and `Octocat` in the README file, you would use the
following query with the *search repositories* endpoint:

```text
GitHub Octocat in:readme user:defunkt
```

**Note:** Be sure to use your language's preferred HTML-encoder to construct your query strings. For example:

```javascript
// JavaScript
const queryString = 'q=' + encodeURIComponent('GitHub Octocat in:readme user:defunkt');
```

See [Searching on GitHub](/en/search-github/searching-on-github)
for a complete list of available qualifiers, their format, and an example of
how to use them. For information about how to use operators to match specific
quantities, dates, or to exclude results, see [Understanding the search syntax](/en/search-github/getting-started-with-searching-on-github/understanding-the-search-syntax).

### Limitations on query length

You cannot use queries that:

* Are longer than 256 characters (not including operators or qualifiers).
* Have more than five `AND`, `OR`, or `NOT` operators.

These search queries will return a "Validation failed" error message.

### Search scope limits

To keep the REST API fast for everyone, we limit the number of repositories a query will search through. The REST API will find up to 4,000 repositories that match your filters and return results from those repositories.

### Timeouts and incomplete results

To keep the REST API fast for everyone, we limit how long any individual query
can run. For queries that [exceed the time limit](https://developer.github.com/changes/2014-04-07-understanding-search-results-and-potential-timeouts/),
the API returns the matches that were already found prior to the timeout, and
the response has the `incomplete_results` property set to `true`.

Reaching a timeout does not necessarily mean that search results are incomplete.
More results might have been found, but also might not.

### Access errors or missing search results

You need to successfully authenticate and have access to the repositories in your search queries, otherwise, you'll see a `422 Unprocessable Entry` error with a "Validation Failed" message. For example, your search will fail if your query includes `repo:`, `user:`, or `org:` qualifiers that request resources that you don't have access to when you sign in on GitHub.

When your search query requests multiple resources, the response will only contain the resources that you have access to and will **not** provide an error message listing the resources that were not returned.

For example, if your search query searches for the `octocat/test` and `codertocat/test` repositories, but you only have access to `octocat/test`, your response will show search results for `octocat/test` and nothing for `codertocat/test`. This behavior mimics how search works on GitHub.

### Text match metadata

On GitHub, you can use the context provided by code snippets and highlights in search results. The endpoints for searching return additional metadata that allows you to highlight the matching search terms when displaying search results.

Requests can opt to receive those text fragments in the response, and every fragment is accompanied by numeric offsets identifying the exact location of each matching search term.

To get this metadata in your search results, specify the `text-match` media type in your `Accept` header.

```shell
application/vnd.github.text-match+json
```

When you provide the `text-match` media type, you will receive an extra key in the JSON payload called `text_matches` that provides information about the position of your search terms within the text and the `property` that includes the search term. Inside the `text_matches` array, each object includes
the following attributes:

| Name          | Description                                                                                                                                                                                                                                                     |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `object_url`  | The URL for the resource that contains a string property matching one of the search terms.                                                                                                                                                                      |
| `object_type` | The name for the type of resource that exists at the given `object_url`.                                                                                                                                                                                        |
| `property`    | The name of a property of the resource that exists at `object_url`. That property is a string that matches one of the search terms. (In the JSON returned from `object_url`, the full content for the `fragment` will be found in the property with this name.) |
| `fragment`    | A subset of the value of `property`. This is the text fragment that matches one or more of the search terms.                                                                                                                                                    |
| `matches`     | An array of one or more search terms that are present in `fragment`. The indices (i.e., "offsets") are relative to the fragment. (They are not relative to the *full* content of `property`.)                                                                   |

#### Example

Using a `curl` command, and the [example issue search](#search-issues-and-pull-requests) above, our API
request would look like this:

```shell
curl -H 'Accept: application/vnd.github.text-match+json' \
'https://api.github.com/search/issues?q=windows+label:bug \
+language:python+state:open&sort=created&order=asc'
```

The response will include a `text_matches` array for each search result. In the JSON below, we have two objects in the `text_matches` array.

The first text match occurred in the `body` property of the issue. We see a fragment of text from the issue body. The search term (`windows`) appears twice within that fragment, and we have the indices for each occurrence.

The second text match occurred in the `body` property of one of the issue's comments. We have the URL for the issue comment. And of course, we see a fragment of text from the comment body. The search term (`windows`) appears once within that fragment.

```json
{
  "text_matches": [
    {
      "object_url": "https://api.github.com/repositories/215335/issues/132",
      "object_type": "Issue",
      "property": "body",
      "fragment": "comprehensive windows font I know of).\n\nIf we can find a commonly
      distributed windows font that supports them then no problem (we can use html
      font tags) but otherwise the '(21)' style is probably better.\n",
      "matches": [
        {
          "text": "windows",
          "indices": [
            14,
            21
          ]
        },
        {
          "text": "windows",
          "indices": [
            78,
            85
          ]
        }
      ]
    },
    {
      "object_url": "https://api.github.com/repositories/215335/issues/comments/25688",
      "object_type": "IssueComment",
      "property": "body",
      "fragment": " right after that are a bit broken IMHO :). I suppose we could
      have some hack that maxes out at whatever the font does...\n\nI'll check
      what the state of play is on Windows.\n",
      "matches": [
        {
          "text": "Windows",
          "indices": [
            163,
            170
          ]
        }
      ]
    }
  ]
}
```

> [!NOTE]
> Most endpoints use `Authorization: Bearer <YOUR-TOKEN>` and `Accept: application/vnd.github+json` headers, plus `X-GitHub-Api-Version: 2026-03-10`. Curl examples below omit these standard headers for brevity.

## Search code

```
GET /search/code
```

Searches for query terms inside of a file. This method returns up to 100 results per page.
When searching for code, you can get text match metadata for the file content and file path fields when you pass the text-match media type. For more details about how to receive highlighted search results, see Text match metadata.
For example, if you want to find the definition of the addClass function inside jQuery repository, your query would look something like this:
q=addClass+in:file+language:js+repo:jquery/jquery
This query searches for the keyword addClass within a file's contents. The query limits the search to files where the language is JavaScript in the jquery/jquery repository.
Considerations for code search:
Due to the complexity of searching code, there are a few restrictions on how searches are performed:

Only the default branch is considered. In most cases, this will be the master branch.
Only files smaller than 384 KB are searchable.
You must always include at least one search term when searching source code. For example, searching for language:go is not valid, while amazing language:go is.

This endpoint requires you to authenticate and limits you to 10 requests per minute.

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`q`** (string) (required)
  The query contains one or more search keywords and qualifiers. Qualifiers allow you to limit your search to specific areas of GitHub. The REST API supports the same qualifiers as the web interface for GitHub. To learn more about the format of the query, see Constructing a search query. See "Searching code" for a detailed list of qualifiers.

* **`sort`** (string)
  This field is closing down. Sorts the results of your query. Can only be indexed, which indicates how recently a file has been indexed by the GitHub search infrastructure. Default: best match
  Can be one of: `indexed`

* **`order`** (string)
  This field is closing down. Determines whether the first search result returned is the highest number of matches (desc) or lowest number of matches (asc). This parameter is ignored unless you provide sort.
  Default: `desc`
  Can be one of: `desc`, `asc`

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

* **403** - Forbidden

* **422** - Validation failed, or the endpoint has been spammed.

* **503** - Service unavailable

### Code examples

#### Example

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/code?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Code Search Result Item`:
  * `name`: required, string
  * `path`: required, string
  * `sha`: required, string
  * `url`: required, string, format: uri
  * `git_url`: required, string, format: uri
  * `html_url`: required, string, format: uri
  * `repository`: required, `Minimal Repository`:
    * `id`: required, integer, format: int64
    * `node_id`: required, string
    * `name`: required, string
    * `full_name`: required, string
    * `owner`: required, `Simple User`:
      * `name`: string or null
      * `email`: string or null
      * `login`: required, string
      * `id`: required, integer, format: int64
      * `node_id`: required, string
      * `avatar_url`: required, string, format: uri
      * `gravatar_id`: required, string or null
      * `url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `followers_url`: required, string, format: uri
      * `following_url`: required, string
      * `gists_url`: required, string
      * `starred_url`: required, string
      * `subscriptions_url`: required, string, format: uri
      * `organizations_url`: required, string, format: uri
      * `repos_url`: required, string, format: uri
      * `events_url`: required, string
      * `received_events_url`: required, string, format: uri
      * `type`: required, string
      * `site_admin`: required, boolean
      * `starred_at`: string
      * `user_view_type`: string
    * `private`: required, boolean
    * `html_url`: required, string, format: uri
    * `description`: required, string or null
    * `fork`: required, boolean
    * `url`: required, string, format: uri
    * `archive_url`: required, string
    * `assignees_url`: required, string
    * `blobs_url`: required, string
    * `branches_url`: required, string
    * `collaborators_url`: required, string
    * `comments_url`: required, string
    * `commits_url`: required, string
    * `compare_url`: required, string
    * `contents_url`: required, string
    * `contributors_url`: required, string, format: uri
    * `deployments_url`: required, string, format: uri
    * `downloads_url`: required, string, format: uri
    * `events_url`: required, string, format: uri
    * `forks_url`: required, string, format: uri
    * `git_commits_url`: required, string
    * `git_refs_url`: required, string
    * `git_tags_url`: required, string
    * `git_url`: string
    * `issue_comment_url`: required, string
    * `issue_events_url`: required, string
    * `issues_url`: required, string
    * `keys_url`: required, string
    * `labels_url`: required, string
    * `languages_url`: required, string, format: uri
    * `merges_url`: required, string, format: uri
    * `milestones_url`: required, string
    * `notifications_url`: required, string
    * `pulls_url`: required, string
    * `releases_url`: required, string
    * `ssh_url`: string
    * `stargazers_url`: required, string, format: uri
    * `statuses_url`: required, string
    * `subscribers_url`: required, string, format: uri
    * `subscription_url`: required, string, format: uri
    * `tags_url`: required, string, format: uri
    * `teams_url`: required, string, format: uri
    * `trees_url`: required, string
    * `clone_url`: string
    * `mirror_url`: string or null
    * `hooks_url`: required, string, format: uri
    * `svn_url`: string
    * `homepage`: string or null
    * `language`: string or null
    * `forks_count`: integer
    * `stargazers_count`: integer
    * `watchers_count`: integer
    * `size`: integer
    * `default_branch`: string
    * `open_issues_count`: integer
    * `is_template`: boolean
    * `topics`: array of string
    * `has_issues`: boolean
    * `has_projects`: boolean
    * `has_wiki`: boolean
    * `has_pages`: boolean
    * `has_discussions`: boolean
    * `has_pull_requests`: boolean
    * `pull_request_creation_policy`: string, enum: `all`, `collaborators_only`
    * `archived`: boolean
    * `disabled`: boolean
    * `visibility`: string
    * `pushed_at`: string or null, format: date-time
    * `created_at`: string or null, format: date-time
    * `updated_at`: string or null, format: date-time
    * `permissions`: object:
      * `admin`: boolean
      * `maintain`: boolean
      * `push`: boolean
      * `triage`: boolean
      * `pull`: boolean
    * `role_name`: string
    * `temp_clone_token`: string
    * `delete_branch_on_merge`: boolean
    * `subscribers_count`: integer
    * `network_count`: integer
    * `code_of_conduct`: `Code Of Conduct`:
      * `key`: required, string
      * `name`: required, string
      * `url`: required, string, format: uri
      * `body`: string
      * `html_url`: required, string or null, format: uri
    * `license`: object or null:
      * `key`: string
      * `name`: string
      * `spdx_id`: string
      * `url`: string or null
      * `node_id`: string
    * `forks`: integer
    * `open_issues`: integer
    * `watchers`: integer
    * `allow_forking`: boolean
    * `web_commit_signoff_required`: boolean
    * `security_and_analysis`: object or null:
      * `advanced_security`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `code_security`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `dependabot_security_updates`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_push_protection`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_non_provider_patterns`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_ai_detection`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_delegated_alert_dismissal`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_delegated_bypass`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_delegated_bypass_options`: object:
        * `reviewers`: array of object
    * `custom_properties`: object, additional properties allowed
  * `score`: required, number
  * `file_size`: integer
  * `language`: string or null
  * `last_modified_at`: string, format: date-time
  * `line_numbers`: array of string
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer

## Search commits

```
GET /search/commits
```

Find commits via various criteria on the default branch (usually main). This method returns up to 100 results per page.
When searching for commits, you can get text match metadata for the message field when you provide the text-match media type. For more details about how to receive highlighted search results, see Text match
metadata.
For example, if you want to find commits related to CSS in the octocat/Spoon-Knife repository. Your query would look something like this:
q=repo:octocat/Spoon-Knife+css

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`q`** (string) (required)
  The query contains one or more search keywords and qualifiers. Qualifiers allow you to limit your search to specific areas of GitHub. The REST API supports the same qualifiers as the web interface for GitHub. To learn more about the format of the query, see Constructing a search query. See "Searching commits" for a detailed list of qualifiers.

* **`sort`** (string)
  Sorts the results of your query by author-date or committer-date. Default: best match
  Can be one of: `author-date`, `committer-date`

* **`order`** (string)
  Determines whether the first search result returned is the highest number of matches (desc) or lowest number of matches (asc). This parameter is ignored unless you provide sort.
  Default: `desc`
  Can be one of: `desc`, `asc`

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

### Code examples

#### Example

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/commits?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Commit Search Result Item`:
  * `url`: required, string, format: uri
  * `sha`: required, string
  * `html_url`: required, string, format: uri
  * `comments_url`: required, string, format: uri
  * `commit`: required, object:
    * `author`: required, object:
      * `name`: required, string
      * `email`: required, string
      * `date`: required, string, format: date-time
    * `committer`: required, any of:
      * **null**
      * **Git User**
        * `name`: string
        * `email`: string
        * `date`: string, format: date-time
    * `comment_count`: required, integer
    * `message`: required, string
    * `tree`: required, object:
      * `sha`: required, string
      * `url`: required, string, format: uri
    * `url`: required, string, format: uri
    * `verification`: `Verification`:
      * `verified`: required, boolean
      * `reason`: required, string
      * `payload`: required, string or null
      * `signature`: required, string or null
      * `verified_at`: required, string or null
  * `author`: required, any of:
    * **null**
    * **Simple User**
      * `name`: string or null
      * `email`: string or null
      * `login`: required, string
      * `id`: required, integer, format: int64
      * `node_id`: required, string
      * `avatar_url`: required, string, format: uri
      * `gravatar_id`: required, string or null
      * `url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `followers_url`: required, string, format: uri
      * `following_url`: required, string
      * `gists_url`: required, string
      * `starred_url`: required, string
      * `subscriptions_url`: required, string, format: uri
      * `organizations_url`: required, string, format: uri
      * `repos_url`: required, string, format: uri
      * `events_url`: required, string
      * `received_events_url`: required, string, format: uri
      * `type`: required, string
      * `site_admin`: required, boolean
      * `starred_at`: string
      * `user_view_type`: string
  * `committer`: required, any of:
    * **null**
    * **Git User** (see above)
  * `parents`: required, array of objects:
    * `url`: string
    * `html_url`: string
    * `sha`: string
  * `repository`: required, `Minimal Repository`:
    * `id`: required, integer, format: int64
    * `node_id`: required, string
    * `name`: required, string
    * `full_name`: required, string
    * `owner`: required, `Simple User` (see above)
    * `private`: required, boolean
    * `html_url`: required, string, format: uri
    * `description`: required, string or null
    * `fork`: required, boolean
    * `url`: required, string, format: uri
    * `archive_url`: required, string
    * `assignees_url`: required, string
    * `blobs_url`: required, string
    * `branches_url`: required, string
    * `collaborators_url`: required, string
    * `comments_url`: required, string
    * `commits_url`: required, string
    * `compare_url`: required, string
    * `contents_url`: required, string
    * `contributors_url`: required, string, format: uri
    * `deployments_url`: required, string, format: uri
    * `downloads_url`: required, string, format: uri
    * `events_url`: required, string, format: uri
    * `forks_url`: required, string, format: uri
    * `git_commits_url`: required, string
    * `git_refs_url`: required, string
    * `git_tags_url`: required, string
    * `git_url`: string
    * `issue_comment_url`: required, string
    * `issue_events_url`: required, string
    * `issues_url`: required, string
    * `keys_url`: required, string
    * `labels_url`: required, string
    * `languages_url`: required, string, format: uri
    * `merges_url`: required, string, format: uri
    * `milestones_url`: required, string
    * `notifications_url`: required, string
    * `pulls_url`: required, string
    * `releases_url`: required, string
    * `ssh_url`: string
    * `stargazers_url`: required, string, format: uri
    * `statuses_url`: required, string
    * `subscribers_url`: required, string, format: uri
    * `subscription_url`: required, string, format: uri
    * `tags_url`: required, string, format: uri
    * `teams_url`: required, string, format: uri
    * `trees_url`: required, string
    * `clone_url`: string
    * `mirror_url`: string or null
    * `hooks_url`: required, string, format: uri
    * `svn_url`: string
    * `homepage`: string or null
    * `language`: string or null
    * `forks_count`: integer
    * `stargazers_count`: integer
    * `watchers_count`: integer
    * `size`: integer
    * `default_branch`: string
    * `open_issues_count`: integer
    * `is_template`: boolean
    * `topics`: array of string
    * `has_issues`: boolean
    * `has_projects`: boolean
    * `has_wiki`: boolean
    * `has_pages`: boolean
    * `has_discussions`: boolean
    * `has_pull_requests`: boolean
    * `pull_request_creation_policy`: string, enum: `all`, `collaborators_only`
    * `archived`: boolean
    * `disabled`: boolean
    * `visibility`: string
    * `pushed_at`: string or null, format: date-time
    * `created_at`: string or null, format: date-time
    * `updated_at`: string or null, format: date-time
    * `permissions`: object:
      * `admin`: boolean
      * `maintain`: boolean
      * `push`: boolean
      * `triage`: boolean
      * `pull`: boolean
    * `role_name`: string
    * `temp_clone_token`: string
    * `delete_branch_on_merge`: boolean
    * `subscribers_count`: integer
    * `network_count`: integer
    * `code_of_conduct`: `Code Of Conduct`:
      * `key`: required, string
      * `name`: required, string
      * `url`: required, string, format: uri
      * `body`: string
      * `html_url`: required, string or null, format: uri
    * `license`: object or null:
      * `key`: string
      * `name`: string
      * `spdx_id`: string
      * `url`: string or null
      * `node_id`: string
    * `forks`: integer
    * `open_issues`: integer
    * `watchers`: integer
    * `allow_forking`: boolean
    * `web_commit_signoff_required`: boolean
    * `security_and_analysis`: object or null:
      * `advanced_security`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `code_security`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `dependabot_security_updates`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_push_protection`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_non_provider_patterns`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_ai_detection`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_delegated_alert_dismissal`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_delegated_bypass`: object:
        * `status`: string, enum: `enabled`, `disabled`
      * `secret_scanning_delegated_bypass_options`: object:
        * `reviewers`: array of object
    * `custom_properties`: object, additional properties allowed
  * `score`: required, number
  * `node_id`: required, string
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer

## Search issues and pull requests

```
GET /search/issues
```

Find issues by state and keyword. This method returns up to 100 results per page.
When searching for issues, you can get text match metadata for the issue title, issue body, and issue comment body fields when you pass the text-match media type. For more details about how to receive highlighted
search results, see Text match metadata.
For example, if you want to find the oldest unresolved Python bugs on Windows. Your query might look something like this.
q=windows+label:bug+language:python+state:open\&sort=created\&order=asc
This query searches for the keyword windows, within any open issue that is labeled as bug. The search runs across repositories whose primary language is Python. The results are sorted by creation date in ascending order, which means the oldest issues appear first in the search results.
Note

For requests made by GitHub Apps with a user access token, you can't retrieve a combination of issues and pull requests in a single query. Requests that don't include the is:issue or is:pull-request qualifier will receive an HTTP 422 Unprocessable Entity response. To get results for both issues and pull requests, you must send separate queries for issues and pull requests. For more information about the is qualifier, see "Searching only issues or pull requests."

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`q`** (string) (required)
  The query contains one or more search keywords and qualifiers. Qualifiers allow you to limit your search to specific areas of GitHub. The REST API supports the same qualifiers as the web interface for GitHub. To learn more about the format of the query, see Constructing a search query. See "Searching issues and pull requests" for a detailed list of qualifiers.

* **`sort`** (string)
  Sorts the results of your query by the number of comments, reactions, reactions-+1, reactions--1, reactions-smile, reactions-thinking\_face, reactions-heart, reactions-tada, or interactions. You can also sort results by how recently the items were created or updated, Default: best match
  Can be one of: `comments`, `reactions`, `reactions-+1`, `reactions--1`, `reactions-smile`, `reactions-thinking_face`, `reactions-heart`, `reactions-tada`, `interactions`, `created`, `updated`

* **`order`** (string)
  Determines whether the first search result returned is the highest number of matches (desc) or lowest number of matches (asc). This parameter is ignored unless you provide sort.
  Default: `desc`
  Can be one of: `desc`, `asc`

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

* **`advanced_search`** (string)
  Set to true to use advanced search.
  Example: <http://api.github.com/search/issues?q={query}&advanced_search=true>

* **`search_type`** (string)
  The type of search to perform on issues. When not specified, the default is lexical search.

  semantic — performs a pure semantic (vector) search using embedding-based understanding.
  hybrid — combines semantic search with lexical search for best results.

  Semantic and hybrid search require authentication and are rate limited to 10 requests per minute.
  Only applies to issue searches (/search/issues).
  Can be one of: `semantic`, `hybrid`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

* **401** - Requires authentication

* **403** - Forbidden

* **422** - Validation failed, or the endpoint has been spammed.

* **503** - Service unavailable

### Code examples

#### Example 1: Status Code 200

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/issues?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Issue Search Result Item`:
  * `url`: required, string, format: uri
  * `repository_url`: required, string, format: uri
  * `labels_url`: required, string
  * `comments_url`: required, string, format: uri
  * `events_url`: required, string, format: uri
  * `html_url`: required, string, format: uri
  * `id`: required, integer, format: int64
  * `node_id`: required, string
  * `number`: required, integer
  * `title`: required, string
  * `locked`: required, boolean
  * `active_lock_reason`: string or null
  * `assignees`: array of `Simple User` or null:
    * `name`: string or null
    * `email`: string or null
    * `login`: required, string
    * `id`: required, integer, format: int64
    * `node_id`: required, string
    * `avatar_url`: required, string, format: uri
    * `gravatar_id`: required, string or null
    * `url`: required, string, format: uri
    * `html_url`: required, string, format: uri
    * `followers_url`: required, string, format: uri
    * `following_url`: required, string
    * `gists_url`: required, string
    * `starred_url`: required, string
    * `subscriptions_url`: required, string, format: uri
    * `organizations_url`: required, string, format: uri
    * `repos_url`: required, string, format: uri
    * `events_url`: required, string
    * `received_events_url`: required, string, format: uri
    * `type`: required, string
    * `site_admin`: required, boolean
    * `starred_at`: string
    * `user_view_type`: string
  * `user`: required, any of:
    * **null**
    * **Simple User** (see above)
  * `labels`: required, array of objects:
    * `id`: integer, format: int64
    * `node_id`: string
    * `url`: string
    * `name`: string
    * `color`: string
    * `default`: boolean
    * `description`: string or null
    * `archived_at`: string or null, format: date-time
    * `archived_by`: all of:
      * **Simple User** (see above)
  * `sub_issues_summary`: `Sub-issues Summary`:
    * `total`: required, integer
    * `completed`: required, integer
    * `percent_completed`: required, integer
  * `issue_dependencies_summary`: `Issue Dependencies Summary`:
    * `blocked_by`: required, integer
    * `blocking`: required, integer
    * `total_blocked_by`: required, integer
    * `total_blocking`: required, integer
  * `issue_field_values`: array of `Issue Field Value`:
    * `issue_field_id`: required, integer, format: int64
    * `issue_field_name`: string
    * `node_id`: required, string
    * `data_type`: required, string, enum: `text`, `single_select`, `multi_select`, `number`, `date`
    * `value`: required, any of:
      * **string**
      * **number**
      * **integer**
    * `single_select_option`: object or null:
      * `id`: required, integer, format: int64
      * `name`: required, string
      * `color`: required, string
    * `multi_select_options`: array of objects or null:
      * `id`: required, integer, format: int64
      * `name`: required, string
      * `color`: required, string
  * `state`: required, string
  * `state_reason`: string or null
  * `milestone`: required, any of:
    * **null**
    * **Milestone**
      * `url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `labels_url`: required, string, format: uri
      * `id`: required, integer
      * `node_id`: required, string
      * `number`: required, integer
      * `state`: required, string, enum: `open`, `closed`, default: `"open"`
      * `title`: required, string
      * `description`: required, string or null
      * `creator`: required, any of:
        * **null**
        * **Simple User** (see above)
      * `open_issues`: required, integer
      * `closed_issues`: required, integer
      * `created_at`: required, string, format: date-time
      * `updated_at`: required, string, format: date-time
      * `closed_at`: required, string or null, format: date-time
      * `due_on`: required, string or null, format: date-time
  * `comments`: required, integer
  * `created_at`: required, string, format: date-time
  * `updated_at`: required, string, format: date-time
  * `closed_at`: required, string or null, format: date-time
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer
  * `pull_request`: object:
    * `merged_at`: string or null, format: date-time
    * `diff_url`: required, string or null, format: uri
    * `html_url`: required, string or null, format: uri
    * `patch_url`: required, string or null, format: uri
    * `url`: required, string or null, format: uri
  * `body`: string
  * `score`: required, number
  * `author_association`: required, string, enum: `COLLABORATOR`, `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, `MANNEQUIN`, `MEMBER`, `NONE`, `OWNER`
  * `draft`: boolean
  * `repository`: `Repository`:
    * `id`: required, integer, format: int64
    * `node_id`: required, string
    * `name`: required, string
    * `full_name`: required, string
    * `license`: required, any of:
      * **null**
      * **License Simple**
        * `key`: required, string
        * `name`: required, string
        * `url`: required, string or null, format: uri
        * `spdx_id`: required, string or null
        * `node_id`: required, string
        * `html_url`: string, format: uri
    * `forks`: required, integer
    * `permissions`: object:
      * `admin`: required, boolean
      * `pull`: required, boolean
      * `triage`: boolean
      * `push`: required, boolean
      * `maintain`: boolean
    * `owner`: required, `Simple User` (see above)
    * `private`: required, boolean, default: `false`
    * `html_url`: required, string, format: uri
    * `description`: required, string or null
    * `fork`: required, boolean
    * `url`: required, string, format: uri
    * `archive_url`: required, string
    * `assignees_url`: required, string
    * `blobs_url`: required, string
    * `branches_url`: required, string
    * `collaborators_url`: required, string
    * `comments_url`: required, string
    * `commits_url`: required, string
    * `compare_url`: required, string
    * `contents_url`: required, string
    * `contributors_url`: required, string, format: uri
    * `deployments_url`: required, string, format: uri
    * `downloads_url`: required, string, format: uri
    * `events_url`: required, string, format: uri
    * `forks_url`: required, string, format: uri
    * `git_commits_url`: required, string
    * `git_refs_url`: required, string
    * `git_tags_url`: required, string
    * `git_url`: required, string
    * `issue_comment_url`: required, string
    * `issue_events_url`: required, string
    * `issues_url`: required, string
    * `keys_url`: required, string
    * `labels_url`: required, string
    * `languages_url`: required, string, format: uri
    * `merges_url`: required, string, format: uri
    * `milestones_url`: required, string
    * `notifications_url`: required, string
    * `pulls_url`: required, string
    * `releases_url`: required, string
    * `ssh_url`: required, string
    * `stargazers_url`: required, string, format: uri
    * `statuses_url`: required, string
    * `subscribers_url`: required, string, format: uri
    * `subscription_url`: required, string, format: uri
    * `tags_url`: required, string, format: uri
    * `teams_url`: required, string, format: uri
    * `trees_url`: required, string
    * `clone_url`: required, string
    * `mirror_url`: required, string or null, format: uri
    * `hooks_url`: required, string, format: uri
    * `svn_url`: required, string, format: uri
    * `homepage`: required, string or null, format: uri
    * `language`: required, string or null
    * `forks_count`: required, integer
    * `stargazers_count`: required, integer
    * `watchers_count`: required, integer
    * `size`: required, integer
    * `default_branch`: required, string
    * `open_issues_count`: required, integer
    * `is_template`: boolean, default: `false`
    * `topics`: array of string
    * `has_issues`: required, boolean, default: `true`
    * `has_projects`: required, boolean, default: `true`
    * `has_wiki`: required, boolean, default: `true`
    * `has_pages`: required, boolean
    * `has_discussions`: boolean, default: `false`
    * `has_pull_requests`: boolean, default: `true`
    * `pull_request_creation_policy`: string, enum: `all`, `collaborators_only`
    * `archived`: required, boolean, default: `false`
    * `disabled`: required, boolean
    * `visibility`: string, default: `"public"`
    * `pushed_at`: required, string or null, format: date-time
    * `created_at`: required, string or null, format: date-time
    * `updated_at`: required, string or null, format: date-time
    * `allow_rebase_merge`: boolean, default: `true`
    * `temp_clone_token`: string
    * `allow_squash_merge`: boolean, default: `true`
    * `allow_auto_merge`: boolean, default: `false`
    * `delete_branch_on_merge`: boolean, default: `false`
    * `allow_update_branch`: boolean, default: `false`
    * `squash_merge_commit_title`: string, enum: `PR_TITLE`, `COMMIT_OR_PR_TITLE`
    * `squash_merge_commit_message`: string, enum: `PR_BODY`, `COMMIT_MESSAGES`, `BLANK`
    * `merge_commit_title`: string, enum: `PR_TITLE`, `MERGE_MESSAGE`
    * `merge_commit_message`: string, enum: `PR_BODY`, `PR_TITLE`, `BLANK`
    * `allow_merge_commit`: boolean, default: `true`
    * `allow_forking`: boolean
    * `web_commit_signoff_required`: boolean, default: `false`
    * `open_issues`: required, integer
    * `watchers`: required, integer
    * `starred_at`: string
    * `anonymous_access_enabled`: boolean
    * `code_search_index_status`: object:
      * `lexical_search_ok`: boolean
      * `lexical_commit_sha`: string
  * `body_html`: string
  * `body_text`: string
  * `timeline_url`: string, format: uri
  * `type`: `Issue Type`:
    * `id`: required, integer
    * `node_id`: required, string
    * `name`: required, string
    * `description`: required, string or null
    * `color`: string or null, enum: `gray`, `blue`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `null`
    * `created_at`: string, format: date-time
    * `updated_at`: string, format: date-time
    * `is_enabled`: boolean
  * `performed_via_github_app`: any of:
    * **null**
    * **GitHub app**
      * `id`: required, integer
      * `slug`: string
      * `node_id`: required, string
      * `client_id`: string
      * `owner`: required, one of:
        * **Simple User** (see above)
        * **Enterprise**
          * `description`: string or null
          * `html_url`: required, string, format: uri
          * `website_url`: string or null, format: uri
          * `id`: required, integer
          * `node_id`: required, string
          * `name`: required, string
          * `slug`: required, string
          * `created_at`: required, string or null, format: date-time
          * `updated_at`: required, string or null, format: date-time
          * `avatar_url`: required, string, format: uri
      * `name`: required, string
      * `description`: required, string or null
      * `external_url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `created_at`: required, string, format: date-time
      * `updated_at`: required, string, format: date-time
      * `permissions`: required, object, additional properties: string:
        * `issues`: string
        * `checks`: string
        * `metadata`: string
        * `contents`: string
        * `deployments`: string
      * `events`: required, array of string
      * `installations_count`: integer
  * `pinned_comment`: any of:
    * **null**
    * **Issue Comment**
      * `id`: required, integer, format: int64
      * `node_id`: required, string
      * `url`: required, string, format: uri
      * `body`: string
      * `body_text`: string
      * `body_html`: string
      * `html_url`: required, string, format: uri
      * `user`: required, any of:
        * **null**
        * **Simple User** (see above)
      * `created_at`: required, string, format: date-time
      * `updated_at`: required, string, format: date-time
      * `issue_url`: required, string, format: uri
      * `author_association`: string, enum: `COLLABORATOR`, `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, `MANNEQUIN`, `MEMBER`, `NONE`, `OWNER`
      * `performed_via_github_app`: any of:
        * **null**
        * **GitHub app** (see above)
      * `reactions`: `Reaction Rollup`:
        * `url`: required, string, format: uri
        * `total_count`: required, integer
        * `+1`: required, integer
        * `-1`: required, integer
        * `laugh`: required, integer
        * `confused`: required, integer
        * `heart`: required, integer
        * `hooray`: required, integer
        * `eyes`: required, integer
        * `rocket`: required, integer
      * `pin`: any of:
        * **null**
        * **Pinned Issue Comment**
          * `pinned_at`: required, string, format: date-time
          * `pinned_by`: required, any of:
            * **null**
            * **Simple User** (see above)
      * `minimized`: any of:
        * **null**
        * **Minimized Issue Comment**
          * `reason`: required, string or null
  * `reactions`: `Reaction Rollup` (see above)
* `search_type`: required, string, enum: `lexical`, `semantic`, `hybrid`
* `lexical_fallback_reason`: array of string, enum: `no_text_terms`, `quoted_text`, `non_issue_target`, `or_boolean_not_supported`, `no_accessible_repos`, `server_error`, `only_non_semantic_fields_requested`, `service_unavailable`

#### Example 2: Status Code 200

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/issues?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Issue Search Result Item`:
  * `url`: required, string, format: uri
  * `repository_url`: required, string, format: uri
  * `labels_url`: required, string
  * `comments_url`: required, string, format: uri
  * `events_url`: required, string, format: uri
  * `html_url`: required, string, format: uri
  * `id`: required, integer, format: int64
  * `node_id`: required, string
  * `number`: required, integer
  * `title`: required, string
  * `locked`: required, boolean
  * `active_lock_reason`: string or null
  * `assignees`: array of `Simple User` or null:
    * `name`: string or null
    * `email`: string or null
    * `login`: required, string
    * `id`: required, integer, format: int64
    * `node_id`: required, string
    * `avatar_url`: required, string, format: uri
    * `gravatar_id`: required, string or null
    * `url`: required, string, format: uri
    * `html_url`: required, string, format: uri
    * `followers_url`: required, string, format: uri
    * `following_url`: required, string
    * `gists_url`: required, string
    * `starred_url`: required, string
    * `subscriptions_url`: required, string, format: uri
    * `organizations_url`: required, string, format: uri
    * `repos_url`: required, string, format: uri
    * `events_url`: required, string
    * `received_events_url`: required, string, format: uri
    * `type`: required, string
    * `site_admin`: required, boolean
    * `starred_at`: string
    * `user_view_type`: string
  * `user`: required, any of:
    * **null**
    * **Simple User** (see above)
  * `labels`: required, array of objects:
    * `id`: integer, format: int64
    * `node_id`: string
    * `url`: string
    * `name`: string
    * `color`: string
    * `default`: boolean
    * `description`: string or null
    * `archived_at`: string or null, format: date-time
    * `archived_by`: all of:
      * **Simple User** (see above)
  * `sub_issues_summary`: `Sub-issues Summary`:
    * `total`: required, integer
    * `completed`: required, integer
    * `percent_completed`: required, integer
  * `issue_dependencies_summary`: `Issue Dependencies Summary`:
    * `blocked_by`: required, integer
    * `blocking`: required, integer
    * `total_blocked_by`: required, integer
    * `total_blocking`: required, integer
  * `issue_field_values`: array of `Issue Field Value`:
    * `issue_field_id`: required, integer, format: int64
    * `issue_field_name`: string
    * `node_id`: required, string
    * `data_type`: required, string, enum: `text`, `single_select`, `multi_select`, `number`, `date`
    * `value`: required, any of:
      * **string**
      * **number**
      * **integer**
    * `single_select_option`: object or null:
      * `id`: required, integer, format: int64
      * `name`: required, string
      * `color`: required, string
    * `multi_select_options`: array of objects or null:
      * `id`: required, integer, format: int64
      * `name`: required, string
      * `color`: required, string
  * `state`: required, string
  * `state_reason`: string or null
  * `milestone`: required, any of:
    * **null**
    * **Milestone**
      * `url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `labels_url`: required, string, format: uri
      * `id`: required, integer
      * `node_id`: required, string
      * `number`: required, integer
      * `state`: required, string, enum: `open`, `closed`, default: `"open"`
      * `title`: required, string
      * `description`: required, string or null
      * `creator`: required, any of:
        * **null**
        * **Simple User** (see above)
      * `open_issues`: required, integer
      * `closed_issues`: required, integer
      * `created_at`: required, string, format: date-time
      * `updated_at`: required, string, format: date-time
      * `closed_at`: required, string or null, format: date-time
      * `due_on`: required, string or null, format: date-time
  * `comments`: required, integer
  * `created_at`: required, string, format: date-time
  * `updated_at`: required, string, format: date-time
  * `closed_at`: required, string or null, format: date-time
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer
  * `pull_request`: object:
    * `merged_at`: string or null, format: date-time
    * `diff_url`: required, string or null, format: uri
    * `html_url`: required, string or null, format: uri
    * `patch_url`: required, string or null, format: uri
    * `url`: required, string or null, format: uri
  * `body`: string
  * `score`: required, number
  * `author_association`: required, string, enum: `COLLABORATOR`, `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, `MANNEQUIN`, `MEMBER`, `NONE`, `OWNER`
  * `draft`: boolean
  * `repository`: `Repository`:
    * `id`: required, integer, format: int64
    * `node_id`: required, string
    * `name`: required, string
    * `full_name`: required, string
    * `license`: required, any of:
      * **null**
      * **License Simple**
        * `key`: required, string
        * `name`: required, string
        * `url`: required, string or null, format: uri
        * `spdx_id`: required, string or null
        * `node_id`: required, string
        * `html_url`: string, format: uri
    * `forks`: required, integer
    * `permissions`: object:
      * `admin`: required, boolean
      * `pull`: required, boolean
      * `triage`: boolean
      * `push`: required, boolean
      * `maintain`: boolean
    * `owner`: required, `Simple User` (see above)
    * `private`: required, boolean, default: `false`
    * `html_url`: required, string, format: uri
    * `description`: required, string or null
    * `fork`: required, boolean
    * `url`: required, string, format: uri
    * `archive_url`: required, string
    * `assignees_url`: required, string
    * `blobs_url`: required, string
    * `branches_url`: required, string
    * `collaborators_url`: required, string
    * `comments_url`: required, string
    * `commits_url`: required, string
    * `compare_url`: required, string
    * `contents_url`: required, string
    * `contributors_url`: required, string, format: uri
    * `deployments_url`: required, string, format: uri
    * `downloads_url`: required, string, format: uri
    * `events_url`: required, string, format: uri
    * `forks_url`: required, string, format: uri
    * `git_commits_url`: required, string
    * `git_refs_url`: required, string
    * `git_tags_url`: required, string
    * `git_url`: required, string
    * `issue_comment_url`: required, string
    * `issue_events_url`: required, string
    * `issues_url`: required, string
    * `keys_url`: required, string
    * `labels_url`: required, string
    * `languages_url`: required, string, format: uri
    * `merges_url`: required, string, format: uri
    * `milestones_url`: required, string
    * `notifications_url`: required, string
    * `pulls_url`: required, string
    * `releases_url`: required, string
    * `ssh_url`: required, string
    * `stargazers_url`: required, string, format: uri
    * `statuses_url`: required, string
    * `subscribers_url`: required, string, format: uri
    * `subscription_url`: required, string, format: uri
    * `tags_url`: required, string, format: uri
    * `teams_url`: required, string, format: uri
    * `trees_url`: required, string
    * `clone_url`: required, string
    * `mirror_url`: required, string or null, format: uri
    * `hooks_url`: required, string, format: uri
    * `svn_url`: required, string, format: uri
    * `homepage`: required, string or null, format: uri
    * `language`: required, string or null
    * `forks_count`: required, integer
    * `stargazers_count`: required, integer
    * `watchers_count`: required, integer
    * `size`: required, integer
    * `default_branch`: required, string
    * `open_issues_count`: required, integer
    * `is_template`: boolean, default: `false`
    * `topics`: array of string
    * `has_issues`: required, boolean, default: `true`
    * `has_projects`: required, boolean, default: `true`
    * `has_wiki`: required, boolean, default: `true`
    * `has_pages`: required, boolean
    * `has_discussions`: boolean, default: `false`
    * `has_pull_requests`: boolean, default: `true`
    * `pull_request_creation_policy`: string, enum: `all`, `collaborators_only`
    * `archived`: required, boolean, default: `false`
    * `disabled`: required, boolean
    * `visibility`: string, default: `"public"`
    * `pushed_at`: required, string or null, format: date-time
    * `created_at`: required, string or null, format: date-time
    * `updated_at`: required, string or null, format: date-time
    * `allow_rebase_merge`: boolean, default: `true`
    * `temp_clone_token`: string
    * `allow_squash_merge`: boolean, default: `true`
    * `allow_auto_merge`: boolean, default: `false`
    * `delete_branch_on_merge`: boolean, default: `false`
    * `allow_update_branch`: boolean, default: `false`
    * `squash_merge_commit_title`: string, enum: `PR_TITLE`, `COMMIT_OR_PR_TITLE`
    * `squash_merge_commit_message`: string, enum: `PR_BODY`, `COMMIT_MESSAGES`, `BLANK`
    * `merge_commit_title`: string, enum: `PR_TITLE`, `MERGE_MESSAGE`
    * `merge_commit_message`: string, enum: `PR_BODY`, `PR_TITLE`, `BLANK`
    * `allow_merge_commit`: boolean, default: `true`
    * `allow_forking`: boolean
    * `web_commit_signoff_required`: boolean, default: `false`
    * `open_issues`: required, integer
    * `watchers`: required, integer
    * `starred_at`: string
    * `anonymous_access_enabled`: boolean
    * `code_search_index_status`: object:
      * `lexical_search_ok`: boolean
      * `lexical_commit_sha`: string
  * `body_html`: string
  * `body_text`: string
  * `timeline_url`: string, format: uri
  * `type`: `Issue Type`:
    * `id`: required, integer
    * `node_id`: required, string
    * `name`: required, string
    * `description`: required, string or null
    * `color`: string or null, enum: `gray`, `blue`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `null`
    * `created_at`: string, format: date-time
    * `updated_at`: string, format: date-time
    * `is_enabled`: boolean
  * `performed_via_github_app`: any of:
    * **null**
    * **GitHub app**
      * `id`: required, integer
      * `slug`: string
      * `node_id`: required, string
      * `client_id`: string
      * `owner`: required, one of:
        * **Simple User** (see above)
        * **Enterprise**
          * `description`: string or null
          * `html_url`: required, string, format: uri
          * `website_url`: string or null, format: uri
          * `id`: required, integer
          * `node_id`: required, string
          * `name`: required, string
          * `slug`: required, string
          * `created_at`: required, string or null, format: date-time
          * `updated_at`: required, string or null, format: date-time
          * `avatar_url`: required, string, format: uri
      * `name`: required, string
      * `description`: required, string or null
      * `external_url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `created_at`: required, string, format: date-time
      * `updated_at`: required, string, format: date-time
      * `permissions`: required, object, additional properties: string:
        * `issues`: string
        * `checks`: string
        * `metadata`: string
        * `contents`: string
        * `deployments`: string
      * `events`: required, array of string
      * `installations_count`: integer
  * `pinned_comment`: any of:
    * **null**
    * **Issue Comment**
      * `id`: required, integer, format: int64
      * `node_id`: required, string
      * `url`: required, string, format: uri
      * `body`: string
      * `body_text`: string
      * `body_html`: string
      * `html_url`: required, string, format: uri
      * `user`: required, any of:
        * **null**
        * **Simple User** (see above)
      * `created_at`: required, string, format: date-time
      * `updated_at`: required, string, format: date-time
      * `issue_url`: required, string, format: uri
      * `author_association`: string, enum: `COLLABORATOR`, `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, `MANNEQUIN`, `MEMBER`, `NONE`, `OWNER`
      * `performed_via_github_app`: any of:
        * **null**
        * **GitHub app** (see above)
      * `reactions`: `Reaction Rollup`:
        * `url`: required, string, format: uri
        * `total_count`: required, integer
        * `+1`: required, integer
        * `-1`: required, integer
        * `laugh`: required, integer
        * `confused`: required, integer
        * `heart`: required, integer
        * `hooray`: required, integer
        * `eyes`: required, integer
        * `rocket`: required, integer
      * `pin`: any of:
        * **null**
        * **Pinned Issue Comment**
          * `pinned_at`: required, string, format: date-time
          * `pinned_by`: required, any of:
            * **null**
            * **Simple User** (see above)
      * `minimized`: any of:
        * **null**
        * **Minimized Issue Comment**
          * `reason`: required, string or null
  * `reactions`: `Reaction Rollup` (see above)
* `search_type`: required, string, enum: `lexical`, `semantic`, `hybrid`
* `lexical_fallback_reason`: array of string, enum: `no_text_terms`, `quoted_text`, `non_issue_target`, `or_boolean_not_supported`, `no_accessible_repos`, `server_error`, `only_non_semantic_fields_requested`, `service_unavailable`

## Search labels

```
GET /search/labels
```

Find labels in a repository with names or descriptions that match search keywords. Returns up to 100 results per page.
When searching for labels, you can get text match metadata for the label name and description fields when you pass the text-match media type. For more details about how to receive highlighted search results, see Text match metadata.
For example, if you want to find labels in the linguist repository that match bug, defect, or enhancement. Your query might look like this:
q=bug+defect+enhancement\&repository\_id=64778136
The labels that best match the query appear first in the search results.

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`repository_id`** (integer) (required)
  The id of the repository.

* **`q`** (string) (required)
  The search keywords. This endpoint does not accept qualifiers in the query. To learn more about the format of the query, see Constructing a search query.

* **`sort`** (string)
  Sorts the results of your query by when the label was created or updated. Default: best match
  Can be one of: `created`, `updated`

* **`order`** (string)
  Determines whether the first search result returned is the highest number of matches (desc) or lowest number of matches (asc). This parameter is ignored unless you provide sort.
  Default: `desc`
  Can be one of: `desc`, `asc`

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

* **403** - Forbidden

* **404** - Resource not found

* **422** - Validation failed, or the endpoint has been spammed.

### Code examples

#### Example

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/labels?repository_id=REPOSITORY_ID&q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Label Search Result Item`:
  * `id`: required, integer
  * `node_id`: required, string
  * `url`: required, string, format: uri
  * `name`: required, string
  * `color`: required, string
  * `default`: required, boolean
  * `description`: required, string or null
  * `archived_at`: required, string or null, format: date-time
  * `archived_by`: required, all of:
    * **Simple User**
      * `name`: string or null
      * `email`: string or null
      * `login`: required, string
      * `id`: required, integer, format: int64
      * `node_id`: required, string
      * `avatar_url`: required, string, format: uri
      * `gravatar_id`: required, string or null
      * `url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `followers_url`: required, string, format: uri
      * `following_url`: required, string
      * `gists_url`: required, string
      * `starred_url`: required, string
      * `subscriptions_url`: required, string, format: uri
      * `organizations_url`: required, string, format: uri
      * `repos_url`: required, string, format: uri
      * `events_url`: required, string
      * `received_events_url`: required, string, format: uri
      * `type`: required, string
      * `site_admin`: required, boolean
      * `starred_at`: string
      * `user_view_type`: string
  * `score`: required, number
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer

## Search repositories

```
GET /search/repositories
```

Find repositories via various criteria. This method returns up to 100 results per page.
When searching for repositories, you can get text match metadata for the name and description fields when you pass the text-match media type. For more details about how to receive highlighted search results, see Text match metadata.
For example, if you want to search for popular Tetris repositories written in assembly code, your query might look like this:
q=tetris+language:assembly\&sort=stars\&order=desc
This query searches for repositories with the word tetris in the name, the description, or the README. The results are limited to repositories where the primary language is assembly. The results are sorted by stars in descending order, so that the most popular repositories appear first in the search results.

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`q`** (string) (required)
  The query contains one or more search keywords and qualifiers. Qualifiers allow you to limit your search to specific areas of GitHub. The REST API supports the same qualifiers as the web interface for GitHub. To learn more about the format of the query, see Constructing a search query. See "Searching for repositories" for a detailed list of qualifiers.

* **`sort`** (string)
  Sorts the results of your query by number of stars, forks, or help-wanted-issues or how recently the items were updated. Default: best match
  Can be one of: `stars`, `forks`, `help-wanted-issues`, `updated`

* **`order`** (string)
  Determines whether the first search result returned is the highest number of matches (desc) or lowest number of matches (asc). This parameter is ignored unless you provide sort.
  Default: `desc`
  Can be one of: `desc`, `asc`

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

* **422** - Validation failed, or the endpoint has been spammed.

* **503** - Service unavailable

### Code examples

#### Example

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/repositories?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Repo Search Result Item`:
  * `id`: required, integer
  * `node_id`: required, string
  * `name`: required, string
  * `full_name`: required, string
  * `owner`: required, any of:
    * **null**
    * **Simple User**
      * `name`: string or null
      * `email`: string or null
      * `login`: required, string
      * `id`: required, integer, format: int64
      * `node_id`: required, string
      * `avatar_url`: required, string, format: uri
      * `gravatar_id`: required, string or null
      * `url`: required, string, format: uri
      * `html_url`: required, string, format: uri
      * `followers_url`: required, string, format: uri
      * `following_url`: required, string
      * `gists_url`: required, string
      * `starred_url`: required, string
      * `subscriptions_url`: required, string, format: uri
      * `organizations_url`: required, string, format: uri
      * `repos_url`: required, string, format: uri
      * `events_url`: required, string
      * `received_events_url`: required, string, format: uri
      * `type`: required, string
      * `site_admin`: required, boolean
      * `starred_at`: string
      * `user_view_type`: string
  * `private`: required, boolean
  * `html_url`: required, string, format: uri
  * `description`: required, string or null
  * `fork`: required, boolean
  * `url`: required, string, format: uri
  * `created_at`: required, string, format: date-time
  * `updated_at`: required, string, format: date-time
  * `pushed_at`: required, string, format: date-time
  * `homepage`: required, string or null, format: uri
  * `size`: required, integer
  * `stargazers_count`: required, integer
  * `watchers_count`: required, integer
  * `language`: required, string or null
  * `forks_count`: required, integer
  * `open_issues_count`: required, integer
  * `master_branch`: string
  * `default_branch`: required, string
  * `score`: required, number
  * `forks_url`: required, string, format: uri
  * `keys_url`: required, string
  * `collaborators_url`: required, string
  * `teams_url`: required, string, format: uri
  * `hooks_url`: required, string, format: uri
  * `issue_events_url`: required, string
  * `events_url`: required, string, format: uri
  * `assignees_url`: required, string
  * `branches_url`: required, string
  * `tags_url`: required, string, format: uri
  * `blobs_url`: required, string
  * `git_tags_url`: required, string
  * `git_refs_url`: required, string
  * `trees_url`: required, string
  * `statuses_url`: required, string
  * `languages_url`: required, string, format: uri
  * `stargazers_url`: required, string, format: uri
  * `contributors_url`: required, string, format: uri
  * `subscribers_url`: required, string, format: uri
  * `subscription_url`: required, string, format: uri
  * `commits_url`: required, string
  * `git_commits_url`: required, string
  * `comments_url`: required, string
  * `issue_comment_url`: required, string
  * `contents_url`: required, string
  * `compare_url`: required, string
  * `merges_url`: required, string, format: uri
  * `archive_url`: required, string
  * `downloads_url`: required, string, format: uri
  * `issues_url`: required, string
  * `pulls_url`: required, string
  * `milestones_url`: required, string
  * `notifications_url`: required, string
  * `labels_url`: required, string
  * `releases_url`: required, string
  * `deployments_url`: required, string, format: uri
  * `git_url`: required, string
  * `ssh_url`: required, string
  * `clone_url`: required, string
  * `svn_url`: required, string, format: uri
  * `forks`: required, integer
  * `open_issues`: required, integer
  * `watchers`: required, integer
  * `topics`: array of string
  * `mirror_url`: required, string or null, format: uri
  * `has_issues`: required, boolean
  * `has_projects`: required, boolean
  * `has_pages`: required, boolean
  * `has_wiki`: required, boolean
  * `has_downloads`: required, boolean
  * `has_discussions`: boolean
  * `has_pull_requests`: boolean
  * `pull_request_creation_policy`: string, enum: `all`, `collaborators_only`
  * `archived`: required, boolean
  * `disabled`: required, boolean
  * `visibility`: string
  * `license`: required, any of:
    * **null**
    * **License Simple**
      * `key`: required, string
      * `name`: required, string
      * `url`: required, string or null, format: uri
      * `spdx_id`: required, string or null
      * `node_id`: required, string
      * `html_url`: string, format: uri
  * `permissions`: object:
    * `admin`: required, boolean
    * `maintain`: boolean
    * `push`: required, boolean
    * `triage`: boolean
    * `pull`: required, boolean
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer
  * `temp_clone_token`: string
  * `allow_merge_commit`: boolean
  * `allow_squash_merge`: boolean
  * `allow_rebase_merge`: boolean
  * `allow_auto_merge`: boolean
  * `delete_branch_on_merge`: boolean
  * `allow_forking`: boolean
  * `is_template`: boolean
  * `web_commit_signoff_required`: boolean

## Search topics

```
GET /search/topics
```

Find topics via various criteria. Results are sorted by best match. This method returns up to 100 results per page. See "Searching topics" for a detailed list of qualifiers.
When searching for topics, you can get text match metadata for the topic's short\_description, description, name, or display\_name field when you pass the text-match media type. For more details about how to receive highlighted search results, see Text match metadata.
For example, if you want to search for topics related to Ruby that are featured on <https://github.com/topics>. Your query might look like this:
q=ruby+is:featured
This query searches for topics with the keyword ruby and limits the results to find only topics that are featured. The topics that are the best match for the query appear first in the search results.

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`q`** (string) (required)
  The query contains one or more search keywords and qualifiers. Qualifiers allow you to limit your search to specific areas of GitHub. The REST API supports the same qualifiers as the web interface for GitHub. To learn more about the format of the query, see Constructing a search query.

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

### Code examples

#### Example

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/topics?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `Topic Search Result Item`:
  * `name`: required, string
  * `display_name`: required, string or null
  * `short_description`: required, string or null
  * `description`: required, string or null
  * `created_by`: required, string or null
  * `released`: required, string or null
  * `created_at`: required, string, format: date-time
  * `updated_at`: required, string, format: date-time
  * `featured`: required, boolean
  * `curated`: required, boolean
  * `score`: required, number
  * `repository_count`: integer or null
  * `logo_url`: string or null, format: uri
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer
  * `related`: array of objects or null:
    * `topic_relation`: object:
      * `id`: integer
      * `name`: string
      * `topic_id`: integer
      * `relation_type`: string
  * `aliases`: array of objects or null:
    * `topic_relation`: object:
      * `id`: integer
      * `name`: string
      * `topic_id`: integer
      * `relation_type`: string

## Search users

```
GET /search/users
```

Find users via various criteria. This method returns up to 100 results per page.
When searching for users, you can get text match metadata for the issue login, public email, and name fields when you pass the text-match media type. For more details about highlighting search results, see Text match metadata. For more details about how to receive highlighted search results, see Text match metadata.
For example, if you're looking for a list of popular users, you might try this query:
q=tom+repos:%3E42+followers:%3E1000
This query searches for users with the name tom. The results are restricted to users with more than 42 repositories and over 1,000 followers.
This endpoint does not accept authentication and will only include publicly visible users. As an alternative, you can use the GraphQL API. The GraphQL API requires authentication and will return private users, including Enterprise Managed Users (EMUs), that you are authorized to view. For more information, see "GraphQL Queries."

### Parameters

#### Headers

* **`accept`** (string)
  Setting to `application/vnd.github+json` is recommended.

#### Path and query parameters

* **`q`** (string) (required)
  The query contains one or more search keywords and qualifiers. Qualifiers allow you to limit your search to specific areas of GitHub. The REST API supports the same qualifiers as the web interface for GitHub. To learn more about the format of the query, see Constructing a search query. See "Searching users" for a detailed list of qualifiers.

* **`sort`** (string)
  Sorts the results of your query by number of followers or repositories, or when the person joined GitHub. Default: best match
  Can be one of: `followers`, `repositories`, `joined`

* **`order`** (string)
  Determines whether the first search result returned is the highest number of matches (desc) or lowest number of matches (asc). This parameter is ignored unless you provide sort.
  Default: `desc`
  Can be one of: `desc`, `asc`

* **`per_page`** (integer)
  The number of results per page (max 100). For more information, see "Using pagination in the REST API."
  Default: `30`

* **`page`** (integer)
  The page number of the results to fetch. For more information, see "Using pagination in the REST API."
  Default: `1`

### HTTP response status codes

* **200** - OK

* **304** - Not modified

* **422** - Validation failed, or the endpoint has been spammed.

* **503** - Service unavailable

### Code examples

#### Example

**Request:**

```curl
curl -L \
  -X GET \
  "https://api.github.com/search/users?q=Q"
```

**Response schema (Status: 200):**

* `total_count`: required, integer
* `incomplete_results`: required, boolean
* `items`: required, array of `User Search Result Item`:
  * `login`: required, string
  * `id`: required, integer, format: int64
  * `node_id`: required, string
  * `avatar_url`: required, string, format: uri
  * `gravatar_id`: required, string or null
  * `url`: required, string, format: uri
  * `html_url`: required, string, format: uri
  * `followers_url`: required, string, format: uri
  * `subscriptions_url`: required, string, format: uri
  * `organizations_url`: required, string, format: uri
  * `repos_url`: required, string, format: uri
  * `received_events_url`: required, string, format: uri
  * `type`: required, string
  * `score`: required, number
  * `following_url`: required, string
  * `gists_url`: required, string
  * `starred_url`: required, string
  * `events_url`: required, string
  * `public_repos`: integer
  * `public_gists`: integer
  * `followers`: integer
  * `following`: integer
  * `created_at`: string, format: date-time
  * `updated_at`: string, format: date-time
  * `name`: string or null
  * `bio`: string or null
  * `email`: string or null, format: email
  * `location`: string or null
  * `site_admin`: required, boolean
  * `hireable`: boolean or null
  * `text_matches`: array of objects:
    * `object_url`: string
    * `object_type`: string or null
    * `property`: string
    * `fragment`: string
    * `matches`: array of objects:
      * `text`: string
      * `indices`: array of integer
  * `blog`: string or null
  * `company`: string or null
  * `suspended_at`: string or null, format: date-time
  * `user_view_type`: string