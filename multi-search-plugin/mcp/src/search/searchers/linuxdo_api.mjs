import { chromium } from "patchright";
import { readFileSync } from "fs";
import { join } from "path";

const query = process.argv[2];
if (!query) {
  console.log(JSON.stringify([]));
  process.exit(0);
}

try {
  const browser = await chromium.launch({ headless: true, timeout: 30000 });
  const page = await browser.newPage();
  const apiUrl = `https://linux.do/search.json?q=${encodeURIComponent(query)}&page=1`;

  var resp = await page.goto(apiUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  var body = await resp.text();
  await browser.close();

  if (body.startsWith("<")) {
    console.log(JSON.stringify([{ source: "linuxdo-api", error: "blocked by Cloudflare" }]));
    process.exit(0);
  }

  var data = JSON.parse(body);
  var posts = (data.posts || []).slice(0, 10).map(p => ({
    source: "linuxdo-api",
    title: (p.blurb || "").slice(0, 200).replace(/\n/g, " "),
    url: `https://linux.do/t/topic/${p.topic_id}`,
    description: `u/${p.username || "?"} | ${p.like_count || 0} likes`,
  }));
  console.log(JSON.stringify(posts));
} catch (e) {
  console.log(JSON.stringify([{ source: "linuxdo-api", error: String(e.message || e).slice(0, 300) }]));
  process.exit(0);
}
