> Source: https://www.algolia.com/doc/api-reference/api-parameters/hitsPerPage
> Retrieved: 2026-10-31
> Covers: hitsPerPage search parameter (used by GET https://hn.algolia.com/api/v1/search)

> ## Documentation Index
> 
> 
> Fetch the complete documentation index at:[/llms.txt](https://www.algolia.com/llms.txt)
> 
> 
> Use this file to discover all available pages before exploring further.

[Skip to main content](https://www.algolia.com/doc/api-reference/api-parameters/hitsPerPage#content-area)

*   **Type:**`integer`
*   **Default:**`20`
*   **Min:**`1`
*   **Max:**`1000`
*   **Scope:**[`settings,search`](https://www.algolia.com/doc/api-reference/api-parameters)

Algolia uses the `page` and `hitsPerPage` parameters to control how search results are [paginated](https://www.algolia.com/doc/guides/building-search-ui/ui-and-ux-patterns/pagination/js). `hitsPerPage` sets the number of search results (hits) displayed per page.With `page` and `hitsPerPage`, the response includes these fields:

```
{
  // ...
  "page": 1,
  "nbPages": 20,
  "hitsPerPage": 10,
  // ...
}
```

## [​](https://www.algolia.com/doc/api-reference/api-parameters/hitsPerPage#examples)

Examples

### [​](https://www.algolia.com/doc/api-reference/api-parameters/hitsPerPage#set-default-number-of-hits-per-page)

Set default number of hits per page

Current API clients

C#

Dart

Go

Java

JavaScript

Kotlin

PHP

Python

Ruby

Scala

Swift

```
var response = await client.SetSettingsAsync(
  "INDEX_NAME",
  new IndexSettings { HitsPerPage = 20 }
);
```

```
final response = await client.setSettings(
  indexName: "INDEX_NAME",
  indexSettings: IndexSettings(
    hitsPerPage: 20,
  ),
);
```

```
response, err := client.SetSettings(client.NewApiSetSettingsRequest(
  "INDEX_NAME",
  search.NewEmptyIndexSettings().SetHitsPerPage(20)))
if err != nil {
  // handle the eventual error
  panic(err)
}
```

```
UpdatedAtResponse response = client.setSettings("INDEX_NAME", new IndexSettings().setHitsPerPage(20));
```

```
const response = await client.setSettings({ indexName: 'theIndexName', indexSettings: { hitsPerPage: 20 } });
```

```
var response =
  client.setSettings(
    indexName = "INDEX_NAME",
    indexSettings = IndexSettings(hitsPerPage = 20),
  )
```

```
$response = $client->setSettings(
    'INDEX_NAME',
    ['hitsPerPage' => 20,
    ],
);
```

```
response = client.set_settings(
    index_name="INDEX_NAME",
    index_settings={
        "hitsPerPage": 20,
    },
)
```

```
response = client.set_settings("INDEX_NAME", Algolia::Search::IndexSettings.new(hits_per_page: 20))
```

```
val response = Await.result(
  client.setSettings(
    indexName = "INDEX_NAME",
    indexSettings = IndexSettings(
      hitsPerPage = Some(20)
    )
  ),
  Duration(100, "sec")
)
```

```
let response = try await client.setSettings(
    indexName: "INDEX_NAME",
    indexSettings: IndexSettings(hitsPerPage: 20)
)
```

Legacy API clients

C#

Go

Java

JavaScript

Kotlin

PHP

Python

Ruby

Scala

Swift

```
IndexSettings settings = new IndexSettings();
settings.HitsPerPage = 20;

index.SetSettings(settings);
```

```
res, err := index.SetSettings(search.Settings{
	opt.HitsPerPage(20),
})
```

```
index.setSettings(
  new IndexSettings().setHitsPerPage(20)
);
```

```
index
  .setSettings({
    hitsPerPage: 20,
  })
  .then(() => {
    // done
  });
```

```
val settings = settings {
    hitsPerPage = 20
}

index.setSettings(settings)
```

```
$index->setSettings([
  'hitsPerPage' => 20
]);
```

```
index.setSettings({"hitsPerPage": 20})
```

```
index.set_settings(
  {
    hitsPerPage: 20
  }
)
```

```
client.execute {
  setSettings of "myIndex" `with` IndexSettings(
    hitsPerPage = Some(20)
  )
}
```

```
let settings = Settings()
  .set(\.hitsPerPage, to: 20)

index.setSettings(settings) { result in
  if case .success(let response) = result {
    print("Response: \(response)")
  }
}
```

### [​](https://www.algolia.com/doc/api-reference/api-parameters/hitsPerPage#override-default-number-of-hits-per-page-for-the-current-search)

Override default number of hits per page for the current search

Current API clients

C#

Dart

Go

Java

JavaScript

Kotlin

PHP

Python

Ruby

Scala

Swift

```
var response = await client.SearchSingleIndexAsync<Hit>(
  "INDEX_NAME",
  new SearchParams(new SearchParamsObject { Query = "query", HitsPerPage = 10 })
);
```

```
final response = await client.searchSingleIndex(
  indexName: "INDEX_NAME",
  searchParams: SearchParamsObject(
    query: "query",
    hitsPerPage: 10,
  ),
);
```

```
response, err := client.SearchSingleIndex(client.NewApiSearchSingleIndexRequest(
  "INDEX_NAME").WithSearchParams(search.SearchParamsObjectAsSearchParams(
  search.NewEmptySearchParamsObject().SetQuery("query").SetHitsPerPage(10))))
if err != nil {
  // handle the eventual error
  panic(err)
}
```

```
SearchResponse response = client.searchSingleIndex(
  "INDEX_NAME",
  new SearchParamsObject().setQuery("query").setHitsPerPage(10),
  Hit.class
);
```

```
const response = await client.searchSingleIndex({
  indexName: 'indexName',
  searchParams: { query: 'query', hitsPerPage: 10 },
});
```

```
var response =
  client.searchSingleIndex(
    indexName = "INDEX_NAME",
    searchParams = SearchParamsObject(query = "query", hitsPerPage = 10),
  )
```

```
$response = $client->searchSingleIndex(
    'INDEX_NAME',
    ['query' => 'query',
        'hitsPerPage' => 10,
    ],
);
```

```
response = client.search_single_index(
    index_name="INDEX_NAME",
    search_params={
        "query": "query",
        "hitsPerPage": 10,
    },
)
```

```
response = client.search_single_index(
  "INDEX_NAME",
  Algolia::Search::SearchParamsObject.new(query: "query", hits_per_page: 10)
)
```

```
val response = Await.result(
  client.searchSingleIndex(
    indexName = "INDEX_NAME",
    searchParams = Some(
      SearchParamsObject(
        query = Some("query"),
        hitsPerPage = Some(10)
      )
    )
  ),
  Duration(100, "sec")
)
```

```
let response: SearchResponse<Hit> = try await client.searchSingleIndex(
    indexName: "INDEX_NAME",
    searchParams: SearchSearchParams.searchSearchParamsObject(SearchSearchParamsObject(
        query: "query",
        hitsPerPage: 10
    ))
)
```

Legacy API clients

C#

Go

Java

JavaScript

Kotlin

PHP

Python

Ruby

Scala

Swift

```
index.Search(new Query("query")
{
    HitsPerPage = 10
});
```

```
res, err := index.Search(
	"query",
	opt.HitsPerPage(10),
)
```

```
index.search(
  new Query("query").setHitsPerPage(10)
);
```

```
index
  .search("query", {
    hitsPerPage: 10,
  })
  .then(({ hits }) => {
    console.log(hits);
  });
```

```
val query = query("query") {
    hitsPerPage = 10
}

index.search(query)
```

```
$results = $index->search('query', [
  'hitsPerPage' => 10
]);
```

```
results = index.search("query", {"hitsPerPage": 10})
```

```
results = index.search(
  "query",
  {
    hitsPerPage: 10
  }
)
```

```
client.execute {
  search into "myIndex" query Query(
    query = Some("query"),
    hitsPerPage = Some(10)
  )
}
```

```
let query = Query("query")
  .set(\.hitsPerPage, to: 10)

index.search(query: query) { result in
  if case .success(let response) = result {
    print("Response: \(response)")
  }
}
```

Last modified on April 28, 2026

Was this page helpful?

Yes No
