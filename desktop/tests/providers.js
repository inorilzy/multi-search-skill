// Test helper: provides the providerList stub the desktop exposes over IPC.
// Mirrors the canonical provider::PROVIDERS table — when the Rust table
// changes, this stub must be updated alongside it. The production UI gets
// the same data from `api.providerList()`; this file is the test seam.

export const PROVIDER_ROWS = [
  { source: 'baidu', cliSource: 'baidu', provider: 'baidu', label: 'Baidu AI 搜索', keyed: true, cookie: false, aliases: ['baidu-ai-search', 'qianfan'] },
  { source: 'brave', cliSource: 'brave', provider: 'brave', label: 'Brave 搜索', keyed: true, cookie: false, aliases: [] },
  { source: 'parallel', cliSource: 'parallel', provider: 'parallel', label: 'Parallel', keyed: true, cookie: false, aliases: [] },
  { source: 'tavily', cliSource: 'tavily', provider: 'tavily', label: 'Tavily', keyed: true, cookie: false, aliases: [] },
  { source: 'exa', cliSource: 'exa', provider: 'exa', label: 'Exa', keyed: true, cookie: false, aliases: [] },
  { source: 'firecrawl', cliSource: 'firecrawl', provider: 'firecrawl', label: 'Firecrawl', keyed: true, cookie: false, aliases: [] },
  { source: 'serpapi', cliSource: 'serpapi', provider: 'serpapi', label: 'SerpAPI', keyed: true, cookie: false, aliases: [] },
  { source: 'github_repos', cliSource: 'github-repos', provider: 'github', label: 'GitHub 仓库', keyed: true, cookie: false, aliases: ['github', 'github-repos'] },
  { source: 'hackernews', cliSource: 'hackernews', provider: null, label: 'Hacker News', keyed: false, cookie: false, aliases: [] },
  { source: 'stackoverflow', cliSource: 'stackoverflow', provider: null, label: 'Stack Overflow', keyed: false, cookie: false, aliases: [] },
  { source: 'sov2ex', cliSource: 'sov2ex', provider: null, label: 'V2EX', keyed: false, cookie: false, aliases: ['v2ex'] },
  { source: 'twitter', cliSource: 'twitter', provider: null, label: 'Twitter', keyed: false, cookie: true, aliases: [] },
];

export function withProviders(api = {}) {
  return { providerList: async () => PROVIDER_ROWS, ...api };
}
