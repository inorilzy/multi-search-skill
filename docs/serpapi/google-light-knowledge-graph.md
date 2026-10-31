> Source: https://serpapi.com/google-light-knowledge-graph
> Retrieved: 2026-10-31
> Covers: GET https://serpapi.com/search (engine=google_light) knowledge_graph response block

# Google Light Knowledge Graph API

For some requests, Google search includes a "Knowledge Graph" block. SerpApi is able to extract and make sense of this information.

  

The API endpoint is `https://serpapi.com/search?engine=google_light`  
  
 Head to the [playground](https://serpapi.com/playground?engine=google_light) for a live and interactive demo.

[](https://serpapi.com/google-light-knowledge-graph#documentation-demo)

q Search query 

Search

Tools

Output:

JSON Markdown

 HTML size: Text size: Show X-Ray borders:- [x]  Show JSON path:- [x]  Show raw JSON:- [x]  Collapse JSON tree:- [x]  Copy output Reset settings 

*   Collapse/expand  
 JSON`CTRL +`

*   Copy JSON path`ALT +`

{
  "search_metadata": {
    "id": "6abd58face4eb099eb09ec6d",
    "status": "Success",
    "json_endpoint": "https://serpapi.com/searches/4vV3W7oCPQmUg6YKj3r9EpAhN_aKmJvPFKBHoAh7MEw/6abd58face4eb099eb09ec6d.json",
    "markdown_endpoint": "https://serpapi.com/searches/4vV3W7oCPQmUg6YKj3r9EpAhN_aKmJvPFKBHoAh7MEw/6abd58face4eb099eb09ec6d.md",
    "created_at": "2026-09-30 18:46:18 UTC",
    "processed_at": "2026-09-30 18:46:18 UTC",
    "google_light_url": "https://www.google.com/search?q=OpenAI&oq=OpenAI&sourceid=chrome&ie=UTF-8&gbv=1",
    "raw_html_file": "https://serpapi.com/searches/4vV3W7oCPQmUg6YKj3r9EpAhN_aKmJvPFKBHoAh7MEw/6abd58face4eb099eb09ec6d.html",
    "total_time_taken": 0.93
  },
  "search_parameters": {
    "engine": "google_light",
    "q": "OpenAI",
    "google_domain": "google.com",
    "device": "desktop"
  },
  "search_information": {
    "query_displayed": "OpenAI",
    "organic_results_state": "Results for exact spelling"
  },
  "organic_results": [
    {
      "position": 1,
      "title": "OpenAI | Research & Deployment",
      "link": "https://openai.com/",
      "displayed_link": "openai.com",
      "snippet": "We believe our research will eventually lead to artificial general intelligence, a system that can solve human-level problems.",
      "sitelinks": {
        "list": [
          {
            "title": "Introducing ChatGPT",
            "link": "https://openai.com/index/chatgpt/"
          },
          {
            "title": "Careers",
            "link": "https://openai.com/careers/"
          },
          {
            "title": "API Platform",
            "link": "https://openai.com/api/"
          },
          {
            "title": "About",
            "link": "https://openai.com/about/"
          }
        ]
      }
    },
    {
      "position": 2,
      "title": "OpenAI - X",
      "link": "https://x.com/OpenAI",
      "displayed_link": "x.com › OpenAI",
      "snippet": "OpenAI&#39;s mission is to ensure that artificial general intelligence benefits all of humanity. ChatGPT Work, and the"
    },
    {
      "position": 3,
      "title": "OpenAI - Wikipedia",
      "link": "https://en.wikipedia.org/wiki/OpenAI",
      "displayed_link": "en.wikipedia.org › wiki › OpenAI",
      "snippet": "OpenAI is an American artificial intelligence (AI) public benefit corporation (PBC) headquartered in San Francisco, California."
    },
    {
      "position": 4,
      "title": "OpenAI - LinkedIn",
      "link": "https://www.linkedin.com/company/openai",
      "displayed_link": "www.linkedin.com › company › openai",
      "snippet": "OpenAI is an AI research and deployment company dedicated to ensuring that general-purpose artificial intelligence benefits all of humanity."
    },
    {
      "position": 5,
      "title": "r/OpenAI - Reddit",
      "link": "https://www.reddit.com/r/OpenAI/",
      "displayed_link": "www.reddit.com › OpenAI",
      "snippet": "OpenAI is an AI research and deployment company. OpenAI&#39;s mission is to create safe and powerful AI that benefits all of humanity.",
      "date": "Dec 11, 2015"
    },
    {
      "position": 6,
      "title": "OpenAI - YouTube",
      "link": "https://www.youtube.com/@OpenAI",
      "displayed_link": "www.youtube.com › @OpenAI",
      "snippet": "OpenAI's mission is to ensure that artificial general intelligence benefits all of humanity. Introducing GPT-6 Astra: the most intelligent and aligned model in ..."
    }
  ],
  "knowledge_graph": {
    "title": "OpenAI",
    "type": "Generative AI company",
    "description": "OpenAI is an American artificial intelligence public benefit corporation headquartered in San Francisco, California. It develops proprietary generative AI models, particularly its generative pre-trained transformer series of large language models.... Wikipedia",
    "source": {
      "name": "Wikipedia",
      "link": "https://en.wikipedia.org/wiki/OpenAI"
    },
    "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTtxfilD9PiD8rgMPAThXE9arXp_ok0NcSSKKrvjMjZr6YsiKcGtvxP4w&s=0",
    "ceo": "Sam Altman (Nov 29, 2023–)",
    "ceo_links": [
      {
        "text": "Sam Altman",
        "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=Sam+Altman&si=APenkKkicnuBo3HChbgOSg9PTrSKjmOZoDYMZFfiLeKjxtW6731BC4FwlmzofrqNpPvzlvhsQOJJ_l03HdttZEGV7NR6t5lWHZqhFi33BOD_elPqeaueWCI7xgJjByInEIlIeMxiUPiIgEW83Y9lfGhALiArdtnrXUJiK0KLQEPczIO_vSi8ZWTMoRB6ShBvuAOkvoAb0qE7DrCkO-cdanM5um9-_VlTQg%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEAk"
      }
    ],
    "founded": "November 20, 2015, San Francisco, CA",
    "founded_links": [
      {
        "text": "San Francisco, CA",
        "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=San+Francisco&si=APenkKnxxBAKu8uEyVJp5QG7kNERIzt0EhsYdVrbw5Is3icMpkPGLdDGGk1tDytAKXEHMBhXiNLd38FF6jQfToGt36CjmhLAHe23wwRjCRRKcdPgsEIpUOuJPtPU3ZxIcVlzQcWNFgUCuwKwcZzfvFKCJOI0J42Zq9DxlOGA8MKXbneqY3zv2ymQ-AUCtJAOxHH1H6HzSKiXa52P2nk9mzOOeE8OqfAchA%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEAs"
      }
    ],
    "cfo": "Sarah Friar",
    "cfo_links": [
      {
        "text": "Sarah Friar",
        "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=Sarah+Friar&si=APenkKmVGdgpMPDQZoEWS8RIAhsqXAKlNLP0B8DNkkiU9KPI0VT4csCZ_ue4cfwwITFgEafvXFwSvbER3M7cbHVagtfTz8cLYQA0X97kNaDowN30IduvJFBhB5HvBshoIUqQmv8idzycpZeZGqgeSaCZOwwHgBVufLFRrJC3ovpPk7UHckQxrCgfTW-Cz3U0pugqi0Xs0TsNgSlz9Eld86hMPqBBJpuNIA%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEA0"
      }
    ],
    "president": "Greg Brockman",
    "president_links": [
      {
        "text": "Greg Brockman",
        "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=Greg+Brockman&si=APenkKmVGdgpMPDQZoEWS8RIAhsqXAKlNLP0B8DNkkiU9KPI0eLxvmAPCaJSaIclfoeDx-LV_xFTw90uBQKemq0yXzFgJNKTMFIQew4md7Ypj1-5L0xE0Yv7lI9-zP-4q-ZbM4WfDAqWjjvJf99W699Mo_s5C1AgrGB92ZUJRZrYjgXPTPsm9ytRdan9XIKEiIjO7-Jh1afkimkVR6mG_JqGmuoyvziH5A%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEA8"
      }
    ]
  },
  "top_stories": [
    {
      "title": "Introducing dots",
      "link": "https://openai.com/index/introducing-dots/",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTgj1X9X22dKCPs8Vw3Do87trgFt7W59ql9qtcyR1LskgsFUbroSR7RNUXO5Q&s",
      "source": "OpenAI",
      "date": "18 hours ago"
    },
    {
      "title": "FTC launches broad investigation into Anthropic, OpenAI",
      "link": "https://www.washingtonpost.com/technology/2026/09/30/ftc-launches-broad-investigation-into-anthropic-openai/",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTyz7vR5PFQUIiobL5LFNNgE9UhU42T4r4frIEsJWoKrN4QG3XJAuo2ahsmww&s",
      "source": "The Washington Post",
      "date": "1 hour ago"
    },
    {
      "title": "OpenAI considered partnering with China and Russia, cozying up to Kanye West — leading to Amodei split: report",
      "link": "https://nypost.com/2026/09/30/business/openai-considered-partnering-with-china-and-russia-cozying-up-to-kanye-west-leading-to-amodei-split-report/",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRZPYhZVM9OloWyd1UZBn3_5VihrTUnIck-QfFp1vTrWgDK3Y6AAEbe8LWD8A&s",
      "source": "New York Post",
      "date": "1 hour ago"
    },
    {
      "title": "Google drops Gems for Skills, joining OpenAI and Anthropic in the shift to agent-ready prompt formats",
      "link": "https://the-decoder.com/google-drops-gems-for-skills-joining-openai-and-anthropic-in-the-shift-to-agent-ready-prompt-formats/",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTkh0pK1_uxntyUy1wzj0C3W0H9xQUMisShYSp9tL1TyM5_4Y8jzVMduAtfyQ&s",
      "source": "The Decoder",
      "date": "26 minutes ago"
    },
    {
      "title": "OpenAI and Synopsys Announce GPT-Synopsys: Frontier Intelligence to Revolutionize Chip Design",
      "link": "https://www.prnewswire.com/news-releases/openai-and-synopsys-announce-gpt-synopsys-frontier-intelligence-to-revolutionize-chip-design-302894874.html",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSB7KW0Z5yrrFHPv0ti7mrjhTq91dz9M9bCju_TS5W-50iGhPEDIwEst1vQrg&s",
      "source": "PR Newswire",
      "date": "17 minutes ago"
    },
    {
      "title": "OpenAI Ignored Employees’ Warnings About Safely Testing A.I. Models",
      "link": "https://www.nytimes.com/2026/09/29/technology/openai-warnings-security.html",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS-4fO0vqA_wPNQFYfctBMDzM7Af_jzPKi8QGU5DWKpsd2IcqZc_2bALGGkPwI3&s",
      "source": "The New York Times",
      "date": "20 hours ago"
    },
    {
      "title": "OpenAI Targets $30 Billion in Funding at $1.4 Trillion Value",
      "link": "https://www.bloomberg.com/news/articles/2026-09-29/openai-targets-30-billion-in-new-funding-at-1-4-trillion-value",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTdc6aC4VAclbxSnnUpmcfJEY_QtloRH2GbJg7oqFNFxSRQyZWDL5X7UHJTCQ&s",
      "source": "Bloomberg.com",
      "date": "21 hours ago"
    },
    {
      "title": "OpenAI DevDay recap: AI lab rolls out Dots agents, Altman and Friar comment on IPO",
      "link": "https://www.cnbc.com/2026/09/29/openai-devday-2026-live-updates.html",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRzMbWqwOlPcf-N9AM-Zas69uosIa_8XYuqKl3Uqb0JxtV3T-eQCXwUeJ4IbQ&s",
      "source": "CNBC",
      "date": "6 hours ago"
    },
    {
      "title": "Exclusive | OpenAI Scraps Release of New AI Model Over Safety Concerns",
      "link": "https://www.wsj.com/tech/ai/openai-chatgpt-model-release-cancel-safety-5a2f9f42",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQaiKJw9wG5M_jXWAOZAoSxrn3ESbDbf2Gj1XQIKVdwksylEUtR47MOFMk4Hw&s",
      "source": "WSJ",
      "date": "1 day ago"
    },
    {
      "title": "Opinion: Why Apple Is “Terrified of Whatever OpenAI Is Building”",
      "link": "https://www.tikr.com/blog/opinion-why-apple-is-terrified-of-whatever-openai-is-building",
      "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ-9PePbA2Cfr22j9k11-3vf2yqbI4Qw7Xvjx-ATQyaatUevnbpS-NnrYl8Vg&s",
      "source": "TIKR.com",
      "date": "5 hours ago"
    }
  ],
  "serpapi_pagination": {
    "current": 1,
    "next": "https://serpapi.com/search.json?device=desktop&engine=google_light&google_domain=google.com&q=OpenAI&start=10&location=Austin%2C+TX%2C+Texas%2C+United+States"
  }
}
*   
**{**…
    *   "search_metadata": 

**{**…
        *   "id": "6abd58face4eb099eb09ec6d",
        *   "status": "Success",
        *   "json_endpoint": "https://serpapi.com/searches/4vV3W7oCPQmUg6YKj3r9EpAhN_aKmJvPFKBHoAh7MEw/6abd58face4eb099eb09ec6d.json",
        *   "markdown_endpoint": "https://serpapi.com/searches/4vV3W7oCPQmUg6YKj3r9EpAhN_aKmJvPFKBHoAh7MEw/6abd58face4eb099eb09ec6d.md",
        *   "created_at": "2026-09-30 18:46:18 UTC",
        *   "processed_at": "2026-09-30 18:46:18 UTC",
        *   "google_light_url": "https://www.google.com/search?q=OpenAI&oq=OpenAI&sourceid=chrome&ie=UTF-8&gbv=1",
        *   "raw_html_file": "https://serpapi.com/searches/4vV3W7oCPQmUg6YKj3r9EpAhN_aKmJvPFKBHoAh7MEw/6abd58face4eb099eb09ec6d.html",
        *   "total_time_taken": 0.93

**}**

,

    *   "search_parameters": 

**{**…
        *   "engine": "google_light",
        *   "q": "OpenAI",
        *   "google_domain": "google.com",
        *   "device": "desktop"

**}**

,

    *   "search_information": 

**{**…
        *   "query_displayed": "OpenAI",
        *   "organic_results_state": "Results for exact spelling"

**}**

,

    *   "organic_results": 

**[**…
        *   
**{**…
            *   "position": 1,
            *   "title": "OpenAI | Research & Deployment",
            *   "link": "https://openai.com/",
            *   "displayed_link": "openai.com",
            *   "snippet": "We believe our research will eventually lead to artificial general intelligence, a system that can solve human-level problems.",
            *   "sitelinks": 

**{**…
                *   "list": 

**[**…
                    *   
**{**…
                        *   "title": "Introducing ChatGPT",
                        *   "link": "https://openai.com/index/chatgpt/"

**}**

,

                    *   
**{**…
                        *   "title": "Careers",
                        *   "link": "https://openai.com/careers/"

**}**

,

                    *   
**{**…
                        *   "title": "API Platform",
                        *   "link": "https://openai.com/api/"

**}**

,

                    *   
**{**…
                        *   "title": "About",
                        *   "link": "https://openai.com/about/"

**}**

**]**

**}**

**}**

,

        *   
**{**…
            *   "position": 2,
            *   "title": "OpenAI - X",
            *   "link": "https://x.com/OpenAI",
            *   "displayed_link": "x.com › OpenAI",
            *   "snippet": "OpenAI&#39;s mission is to ensure that artificial general intelligence benefits all of humanity. ChatGPT Work, and the"

**}**

,

        *   
**{**…
            *   "position": 3,
            *   "title": "OpenAI - Wikipedia",
            *   "link": "https://en.wikipedia.org/wiki/OpenAI",
            *   "displayed_link": "en.wikipedia.org › wiki › OpenAI",
            *   "snippet": "OpenAI is an American artificial intelligence (AI) public benefit corporation (PBC) headquartered in San Francisco, California."

**}**

,

        *   
**{**…
            *   "position": 4,
            *   "title": "OpenAI - LinkedIn",
            *   "link": "https://www.linkedin.com/company/openai",
            *   "displayed_link": "www.linkedin.com › company › openai",
            *   "snippet": "OpenAI is an AI research and deployment company dedicated to ensuring that general-purpose artificial intelligence benefits all of humanity."

**}**

,

        *   
**{**…
            *   "position": 5,
            *   "title": "r/OpenAI - Reddit",
            *   "link": "https://www.reddit.com/r/OpenAI/",
            *   "displayed_link": "www.reddit.com › OpenAI",
            *   "snippet": "OpenAI is an AI research and deployment company. OpenAI&#39;s mission is to create safe and powerful AI that benefits all of humanity.",
            *   "date": "Dec 11, 2015"

**}**

,

        *   
**{**…
            *   "position": 6,
            *   "title": "OpenAI - YouTube",
            *   "link": "https://www.youtube.com/@OpenAI",
            *   "displayed_link": "www.youtube.com › @OpenAI",
            *   "snippet": "OpenAI's mission is to ensure that artificial general intelligence benefits all of humanity. Introducing GPT-6 Astra: the most intelligent and aligned model in ..."

**}**

**]**

,

    *   "knowledge_graph": 

**{**…
        *   "title": "OpenAI",
        *   "type": "Generative AI company",
        *   "description": "OpenAI is an American artificial intelligence public benefit corporation headquartered in San Francisco, California. It develops proprietary generative AI models, particularly its generative pre-trained transformer series of large language models.... Wikipedia",
        *   "source": 

**{**…
            *   "name": "Wikipedia",
            *   "link": "https://en.wikipedia.org/wiki/OpenAI"

**}**

,

        *   "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTtxfilD9PiD8rgMPAThXE9arXp_ok0NcSSKKrvjMjZr6YsiKcGtvxP4w&s=0",
        *   "ceo": "Sam Altman (Nov 29, 2023–)",
        *   "ceo_links": 

**[**…
            *   
**{**…
                *   "text": "Sam Altman",
                *   "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=Sam+Altman&si=APenkKkicnuBo3HChbgOSg9PTrSKjmOZoDYMZFfiLeKjxtW6731BC4FwlmzofrqNpPvzlvhsQOJJ_l03HdttZEGV7NR6t5lWHZqhFi33BOD_elPqeaueWCI7xgJjByInEIlIeMxiUPiIgEW83Y9lfGhALiArdtnrXUJiK0KLQEPczIO_vSi8ZWTMoRB6ShBvuAOkvoAb0qE7DrCkO-cdanM5um9-_VlTQg%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEAk"

**}**

**]**

,

        *   "founded": "November 20, 2015, San Francisco, CA",
        *   "founded_links": 

**[**…
            *   
**{**…
                *   "text": "San Francisco, CA",
                *   "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=San+Francisco&si=APenkKnxxBAKu8uEyVJp5QG7kNERIzt0EhsYdVrbw5Is3icMpkPGLdDGGk1tDytAKXEHMBhXiNLd38FF6jQfToGt36CjmhLAHe23wwRjCRRKcdPgsEIpUOuJPtPU3ZxIcVlzQcWNFgUCuwKwcZzfvFKCJOI0J42Zq9DxlOGA8MKXbneqY3zv2ymQ-AUCtJAOxHH1H6HzSKiXa52P2nk9mzOOeE8OqfAchA%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEAs"

**}**

**]**

,

        *   "cfo": "Sarah Friar",
        *   "cfo_links": 

**[**…
            *   
**{**…
                *   "text": "Sarah Friar",
                *   "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=Sarah+Friar&si=APenkKmVGdgpMPDQZoEWS8RIAhsqXAKlNLP0B8DNkkiU9KPI0VT4csCZ_ue4cfwwITFgEafvXFwSvbER3M7cbHVagtfTz8cLYQA0X97kNaDowN30IduvJFBhB5HvBshoIUqQmv8idzycpZeZGqgeSaCZOwwHgBVufLFRrJC3ovpPk7UHckQxrCgfTW-Cz3U0pugqi0Xs0TsNgSlz9Eld86hMPqBBJpuNIA%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEA0"

**}**

**]**

,

        *   "president": "Greg Brockman",
        *   "president_links": 

**[**…
            *   
**{**…
                *   "text": "Greg Brockman",
                *   "link": "https://www.google.com/search?sca_esv=e6b59a3d51ae05de&gbv=1&sxsrf=APpeQnun-Xjy7dxHFbH1KLd6uPyxJtpr9Q:1790793984306&q=Greg+Brockman&si=APenkKmVGdgpMPDQZoEWS8RIAhsqXAKlNLP0B8DNkkiU9KPI0eLxvmAPCaJSaIclfoeDx-LV_xFTw90uBQKemq0yXzFgJNKTMFIQew4md7Ypj1-5L0xE0Yv7lI9-zP-4q-ZbM4WfDAqWjjvJf99W699Mo_s5C1AgrGB92ZUJRZrYjgXPTPsm9ytRdan9XIKEiIjO7-Jh1afkimkVR6mG_JqGmuoyvziH5A%3D%3D&sa=X&ved=2ahUKEwiZpbO6-5aXAxXPw8kDHYGLAQ8QmxN6BAgMEA8"

**}**

**]**

**}**

,

    *   "top_stories": 

**[**…
        *   
**{**…
            *   "title": "Introducing dots",
            *   "link": "https://openai.com/index/introducing-dots/",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTgj1X9X22dKCPs8Vw3Do87trgFt7W59ql9qtcyR1LskgsFUbroSR7RNUXO5Q&s",
            *   "source": "OpenAI",
            *   "date": "18 hours ago"

**}**

,

        *   
**{**…
            *   "title": "FTC launches broad investigation into Anthropic, OpenAI",
            *   "link": "https://www.washingtonpost.com/technology/2026/09/30/ftc-launches-broad-investigation-into-anthropic-openai/",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTyz7vR5PFQUIiobL5LFNNgE9UhU42T4r4frIEsJWoKrN4QG3XJAuo2ahsmww&s",
            *   "source": "The Washington Post",
            *   "date": "1 hour ago"

**}**

,

        *   
**{**…
            *   "title": "OpenAI considered partnering with China and Russia, cozying up to Kanye West — leading to Amodei split: report",
            *   "link": "https://nypost.com/2026/09/30/business/openai-considered-partnering-with-china-and-russia-cozying-up-to-kanye-west-leading-to-amodei-split-report/",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRZPYhZVM9OloWyd1UZBn3_5VihrTUnIck-QfFp1vTrWgDK3Y6AAEbe8LWD8A&s",
            *   "source": "New York Post",
            *   "date": "1 hour ago"

**}**

,

        *   
**{**…
            *   "title": "Google drops Gems for Skills, joining OpenAI and Anthropic in the shift to agent-ready prompt formats",
            *   "link": "https://the-decoder.com/google-drops-gems-for-skills-joining-openai-and-anthropic-in-the-shift-to-agent-ready-prompt-formats/",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTkh0pK1_uxntyUy1wzj0C3W0H9xQUMisShYSp9tL1TyM5_4Y8jzVMduAtfyQ&s",
            *   "source": "The Decoder",
            *   "date": "26 minutes ago"

**}**

,

        *   
**{**…
            *   "title": "OpenAI and Synopsys Announce GPT-Synopsys: Frontier Intelligence to Revolutionize Chip Design",
            *   "link": "https://www.prnewswire.com/news-releases/openai-and-synopsys-announce-gpt-synopsys-frontier-intelligence-to-revolutionize-chip-design-302894874.html",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSB7KW0Z5yrrFHPv0ti7mrjhTq91dz9M9bCju_TS5W-50iGhPEDIwEst1vQrg&s",
            *   "source": "PR Newswire",
            *   "date": "17 minutes ago"

**}**

,

        *   
**{**…
            *   "title": "OpenAI Ignored Employees’ Warnings About Safely Testing A.I. Models",
            *   "link": "https://www.nytimes.com/2026/09/29/technology/openai-warnings-security.html",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS-4fO0vqA_wPNQFYfctBMDzM7Af_jzPKi8QGU5DWKpsd2IcqZc_2bALGGkPwI3&s",
            *   "source": "The New York Times",
            *   "date": "20 hours ago"

**}**

,

        *   
**{**…
            *   "title": "OpenAI Targets $30 Billion in Funding at $1.4 Trillion Value",
            *   "link": "https://www.bloomberg.com/news/articles/2026-09-29/openai-targets-30-billion-in-new-funding-at-1-4-trillion-value",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTdc6aC4VAclbxSnnUpmcfJEY_QtloRH2GbJg7oqFNFxSRQyZWDL5X7UHJTCQ&s",
            *   "source": "Bloomberg.com",
            *   "date": "21 hours ago"

**}**

,

        *   
**{**…
            *   "title": "OpenAI DevDay recap: AI lab rolls out Dots agents, Altman and Friar comment on IPO",
            *   "link": "https://www.cnbc.com/2026/09/29/openai-devday-2026-live-updates.html",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRzMbWqwOlPcf-N9AM-Zas69uosIa_8XYuqKl3Uqb0JxtV3T-eQCXwUeJ4IbQ&s",
            *   "source": "CNBC",
            *   "date": "6 hours ago"

**}**

,

        *   
**{**…
            *   "title": "Exclusive | OpenAI Scraps Release of New AI Model Over Safety Concerns",
            *   "link": "https://www.wsj.com/tech/ai/openai-chatgpt-model-release-cancel-safety-5a2f9f42",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQaiKJw9wG5M_jXWAOZAoSxrn3ESbDbf2Gj1XQIKVdwksylEUtR47MOFMk4Hw&s",
            *   "source": "WSJ",
            *   "date": "1 day ago"

**}**

,

        *   
**{**…
            *   "title": "Opinion: Why Apple Is “Terrified of Whatever OpenAI Is Building”",
            *   "link": "https://www.tikr.com/blog/opinion-why-apple-is-terrified-of-whatever-openai-is-building",
            *   "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ-9PePbA2Cfr22j9k11-3vf2yqbI4Qw7Xvjx-ATQyaatUevnbpS-NnrYl8Vg&s",
            *   "source": "TIKR.com",
            *   "date": "5 hours ago"

**}**

**]**

,

    *   "serpapi_pagination": 

**{**…
        *   "current": 1,
        *   "next": "https://serpapi.com/search.json?device=desktop&engine=google_light&google_domain=google.com&q=OpenAI&start=10&location=Austin%2C+TX%2C+Texas%2C+United+States"

**}**

**}**

  

GET

*    
```url
https://serpapi.com/search.json?q=OpenAI&engine=google_light
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  q: "OpenAI",
  engine: "google_light",
  api_key: "secret_api_key"
)

results = client.search
knowledge_graph_title = results[:knowledge_graph][:title]
```

Free Plan · 250 searches / month

[Get started](https://serpapi.com/users/sign_up?plan=free)

## [](https://serpapi.com/google-light-knowledge-graph#api-examples)API examples

### [](https://serpapi.com/google-light-knowledge-graph#api-examples-results-for-apple) Results for: `Apple`

GET

*    
```url
https://serpapi.com/search.json?q=Apple&engine=google_light
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  q: "Apple",
  engine: "google_light",
  api_key: "secret_api_key"
)

results = client.search
knowledge_graph = results[:knowledge_graph]
```

  

JSON Example

[](https://serpapi.com/playground?q=Apple&engine=google_light&highlight=knowledge_graph)

```json
{
  ...
  "knowledge_graph": {
    "title": "Apple",
    "type": "Technology company",
    "website": "http://www.apple.com/",
    "description": "Apple Inc. is an American multinational corporation and technology company headquartered in Cupertino, California, in Silicon Valley. It designs, develops, and sells consumer electronics, computer software, and online services.",
    "source": {
      "name": "Wikipedia",
      "link": "https://en.wikipedia.org/wiki/Apple_Inc."
    },
    "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQwGQRv5TjjkycpctY66mOg_e2-npacrmjAb6_jAWhzlzkFE3OTjxyzbA&s=0",
    "customer_service": "1 (800) 275-2273",
    "founders": "Steve Jobs, Steve Wozniak, and Ronald Wayne",
    "founders_links": [
      {
        "text": "Steve Jobs",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Steve+Jobs&si=ACC90nyvvWro6QmnyY1IfSdgk5wwjB1r8BGd_IWRjXqmKPQqm0U8ySDGNgCC1l3uRMz5JTIEwzV5fp-MGHk1jIUqUP-Xo7U19lJ4OtD-Jf20XsnS_MPLO_cOTeSxnjI7CQtV5BE94f8lfECHp-Lhqs9VxLXAxdbQPa2D_Pa93oq5vjf1ut9Rm32tMxcNBQ1nKXzDifsEzoMqpXo_pMqWu0DDbgqYOd6Ct_TIau51qGdWKmdmXvQHLhneGhXvdC2FoLWVgEzNugr-&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEAs"
      },
      {
        "text": "Steve Wozniak",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Steve+Wozniak&si=ACC90nyvvWro6QmnyY1IfSdgk5wwjB1r8BGd_IWRjXqmKPQqmzwchcj3V8PJgy6YZolRlDdI1hSlp33RpmoWKGaP6Kz3UHsoPt8USSQI2-Y1AWu1CkzirdzibVcUIk9wwKb5U1DhRH7pYte8eRbrxmcfaxpXrjWLCKIaPxvBputcyptmzMQH0PURG6co-GkbrOkefCUF9Xz3fEB2N2l37YzB4ogRnyXTfFFz87pvASuTqdI2lW8z089Lh9ALJD0Cja9F-AUl8yZd&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEAw"
      },
      {
        "text": "Ronald Wayne",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Ronald+Wayne&si=ACC90nzx_D3_zUKRnpAjmO0UBLNxnt7EyN4YYdru6U3bxLI-L4WOg-e7G9kcs8X4NRXFJRVyvKKCKqkpKUei0pAo7vRLY8PhCMtnCiHu0VZ8UTn-WpDlSpek6-GEwgJtJqGC3uMePj2kiiUSIJzvcrYXnlTpD-c9Up_zUoYCcNxU9C0tlGlxOQrLCHlapJrF1TfHB97ufiSSRKdtN01wML6IpVgctD-Q4lWsB1xYTa1FhVK32XoTPzKaHlJqSKVI-bHSaYhtBbrM&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEA0"
      }
    ],
    "ceo": "Tim Cook (Aug 24, 2011–)",
    "ceo_links": [
      {
        "text": "Tim Cook",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Tim+Cook&si=ACC90nzx_D3_zUKRnpAjmO0UBLNxnt7EyN4YYdru6U3bxLI-L2WczUpwGXSJZ8j6_pz-koQ6mEJLqFphtJkwUiFMeiSxrJEugWpKSstRIooQ1JfjOsq41cYLP43z0MpY8d-4Scak4PK91dsOkNmMNo8yQ8_09Qa5avSwoUtGdOjaJP2cYFHDN4SaQec_vGSLGZRmaFLGdxds&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEA8"
      }
    ],
    "coo": "Jeff Williams",
    "coo_links": [
      {
        "text": "Jeff Williams",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Jeff+Williams+(Apple)&si=ACC90nyByJNAHfkzzi7l4JA4fcQKXOYDCI7plJH6uVksGWg6XjzOAYb46qfXnCv-TVPbZiRuVd6LuSDCEOMbLFREdXtDXjPLhLFNoCdvDkSj4uugJuUc7kmloBIu9e6OnlQ-O7RmqU4mOUjuR7NMWa-CvHDvz3HGSS9I60MeK_WGdOu05SzdJz3aIRjoLAXWy1EPkGsLSkf8Z3KCuBdZPB_4_Xl1KigVYw%3D%3D&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEBE"
      }
    ],
    "subsidiaries": "Apple Store, Beats Electronics, Apple Studios, and more",
    "subsidiaries_links": [
      {
        "text": "Apple Store",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Apple+Store&si=ACC90nzx_D3_zUKRnpAjmO0UBLNxnt7EyN4YYdru6U3bxLI-L-ToD2qdDdM9mPYUST5jbkfPEBhBkUX4-wmdsLe85-Y6T2sDTVss3vX8wTgxrfasBfGmTrPMITHTRmzjNw3BD8Bp3rELtYbkEEksBMtyLoiXri2-qtj2fMq24zIORJVka-hR35xlsfD5gCHWI40WI03zTQyu_OB1y4TgzSZin7YGBUsNUUod8uYB2Xwy2PuhIyfpz3rnBRAoGF7Kt0UJdwho9CblpMTtRvqtIvCPmJEig8ZGPw%3D%3D&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEBM"
      },
      {
        "text": "Beats Electronics",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Beats+By+Dre&si=ACC90ny8E30vD16OoPAAI4cStfcliGy35W8UAhb0TsHNc_ISQZzbyUJcqNayyYT3JNobE1Snr67Lqq2wD2Wo3BaEFVqSyqbI719abdnb_jm44Zt2M4vmgn7zivko3I7tLMSftDJITY9dw1cYDfd3WGFs-5vxbElOPGq798ffhVqf7DWn2S6DKDUxhmspJ4f5Svm-apO52KMs9lGFxgsCO4deNbKNHt7BgA6R6ndaX5ShtL1hh2hemmByF90_8jhDThNFs4K3Ua5FBZqZ4KFd68nscrXuCgwEag%3D%3D&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEBQ"
      },
      {
        "text": "Apple Studios",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Apple+Studios&si=ACC90nwLLwns5sISZcdzuISy7t-NHozt8Cbt6G3WNQfC9ekAgIUNmop28cwAxclTSO-SFbyVbu-uBd79wY0DTR11RFkMudgHdy39Qd6L1rdE4AYvLJGpqCN0VrAceiBcl1v59J5FRYn5qyrRyvUBNs-QNQdpZU70pDEK7fPQ-ZzXmH3bABhZfVH7qqIfB4H9tjEpfvr1euVxEzFMpnhhf2X-qAFpUJRbd8hDo0byUWLf_qBLU5QJZt-SSR8zWVFy89o3GivTr9mRvl0ioDrzO2A7DAvhGgrWLfTNZ5zWfsJezmJkNOMrrp0%3D&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEBU"
      },
      {
        "text": "more",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&ei=hbJFZo6fDMXQkPIP7Za6iAY&q=apple+subsidiaries&stick=H4sIAAAAAAAAAOPgE2LXz9U3yLao0tLMKLfST87PyUlNLsnMz9PPL0pPzMusSgRxiq2KS5OKM1MyE4syU4sBS_oD7TYAAAA"
      }
    ],
    "founded": "April 1, 1976, Los Altos, CA",
    "founded_links": [
      {
        "text": "Los Altos, CA",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Los+Altos&si=ACC90nyvvWro6QmnyY1IfSdgk5wwjB1r8BGd_IWRjXqmKPQqm2mLMEauAnIhfSn00FGS8IwLBWLYBNPmUXvIddIebNURGuoZDQDKzGafHWbErNIlpMo1uNxsIySh_p-FC9RSTCAqv7I-1igOzWj0o1qZskfUUdq27DATi82pvAXeLqnfT1tkBqD_Qxc1zIOYn3pKyuLlhGB7&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEBc"
      }
    ],
    "headquarters": "Cupertino, CA",
    "headquarters_links": [
      {
        "text": "Cupertino, CA",
        "link": "https://www.google.com/search?sca_esv=c22fddfe247c1d12&hl=en&gbv=1&gl=us&q=Cupertino&si=ACC90nyvvWro6QmnyY1IfSdgk5wwjB1r8BGd_IWRjXqmKPQqm_8pBiw5xV3gy1pdxjUh3G4z1VDu3LB7Jh1xy1AwcIyL2skT5tVzTWKqFbPmnasFgbdDB7_L4kRIwrQgxJVgtQnfGdFHKkd1OpI2XJfNq5VWk6IruB5HXnEvPoC-QgjLoGUPQaGYmotVAyPiIbEr8mLQRKgn&sa=X&ved=2ahUKEwjO9YP6z5GGAxVFKEQIHW2LDmEQmxN6BAgKEBk"
      }
    ]
  },
  ...
}
```

### [](https://serpapi.com/google-light-knowledge-graph#api-examples-results-for-louvre) Results for: `Louvre`

GET

*    
```url
https://serpapi.com/search.json?q=louvre&engine=google_light
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  q: "louvre",
  engine: "google_light",
  api_key: "secret_api_key"
)

results = client.search
knowledge_graph = results[:knowledge_graph]
```

  

JSON Example

[](https://serpapi.com/playground?q=louvre&engine=google_light&highlight=knowledge_graph)

```json
{
  ...
  "knowledge_graph": {
    "title": "Louvre Museum",
    "type": "Museum in Paris, France",
    "description": "The Louvre, or the Louvre Museum, is a national art museum in Paris, France. It is located on the Right Bank of the Seine in the city's 1st arrondissement and home to some of the most canonical works of Western art, including the Mona Lisa, Venus de Milo, and Winged Victory.",
    "image": "https://lh5.googleusercontent.com/p/AF1QipM_ApMgFfAP8CP2ZHJUOb13K7P_SqSkW9sh9MFY=w72-h72-n-k-no",
    "rating": 4.7,
    "reviews": 312499,
    "directions": "https://maps.google.com/maps?filter=0&gl=us&gbv=1&hl=en&um=1&ie=UTF-8&fb=1&sa=X&geocode=KQ97k3fYceZHMdSELxn6_HW5&daddr=Louvre+Museum,+75001+Paris,+France&ved=1t:7572&ictx=111",
    "website": "https://www.louvre.fr/",
    "address": "75001 Paris, France",
    "hours": "Open ⋅ Closes 9:45 PM",
    "phone": "+33 1 40 20 53 17 ⋅ +33 1 40 20 50 50"
  },
  ...
}
```

### [](https://serpapi.com/google-light-knowledge-graph#api-examples-results-for-dark-tv-series) Results for: `Dark Tv Series`

GET

*    
```url
https://serpapi.com/search.json?q=Dark+Tv+Series&engine=google_light
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  q: "Dark Tv Series",
  engine: "google_light",
  api_key: "secret_api_key"
)

results = client.search
knowledge_graph = results[:knowledge_graph]
```

  

JSON Example

[](https://serpapi.com/playground?q=Dark+Tv+Series&engine=google_light&highlight=knowledge_graph)

```json
{
  ...
  "knowledge_graph": {
    "title": "Dark",
    "type": "2017 ‧ Thriller ‧ 3 seasons",
    "description": "When two children go missing in a small German town, its sinful past is exposed along with the double lives and fractured relationships that exist among four families as they search for the kids. The mystery-drama series introduces an intricate...",
    "header_images": [
      {
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTS4dad5SUZ3laGEdXFHV7CYsBuy4Daz_4zNGtJxg&s=0",
        "source": "https://en.wikipedia.org/wiki/Dark_(TV_series)"
      },
      {
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQkEsmc00rN-4JA85jD-l3uJ4UPLKocZdB3bxFKgA&s=0",
        "source": "https://www.imdb.com/title/tt5753856/"
      },
      {
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT2ADos2HDPhNfZTdhvzOHQmOlDvru_kcs60lGNT3o&s=0",
        "source": "https://www.forbes.com/sites/paultassi/2020/07/11/netflixs-dark-is-the-most-mentally-exhausting-show-ive-ever-seen-but-one-of-sci-fis-best/"
      },
      {
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTNXVsO8BsXHONCV7lneSRJrZ_xPMHhmlsWim6Y9To&s=0",
        "source": "https://www.imdb.com/title/tt5753856/"
      }
    ],
    "editorial_reviews": [
      {
        "title": "IMDb",
        "rating": "8.7/10",
        "link": "https://www.imdb.com/title/tt5753856/"
      },
      {
        "title": "Rotten Tomatoes",
        "rating": "95%",
        "link": "https://www.rottentomatoes.com/tv/dark"
      }
    ],
    "languages": "German and German Sign Language",
    "languages_links": [
      {
        "text": "German Sign Language",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=German+Sign+Language&si=ACC90nzx_D3_zUKRnpAjmO0UBLNxnt7EyN4YYdru6U3bxLI-L6bV1NpMw-UQ9rSez5K6kKI0-5TDgvysjHfcZZQdSEXKKHBFQOS64B-vhtXR9bc_sn_745si2CC2Ll7nTmIdBc-yEXbJnjmukmiIT9z6OIFqB-nf39VAyo6ndvDCOWS67PufA6WlPKyoG8TWS_6ci4H-LCORXgVt0Q4XPqs13Zz87s-ZvxCicLIy6TT_8ZCt_2odasjHaoC2-jhERLpssykkm1dd608Vh6hL21ewQwdaSfllr0FE75P27eTLDH9IC0ufO9s%3D&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQmxN6BAgMEBQ"
      }
    ],
    "composer": "Ben Frost",
    "composer_links": [
      {
        "text": "Ben Frost",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=Ben+Frost&stick=H4sIAAAAAAAAAOPgE-LVT9c3NEwuNksvqciOV-LSz9U3MCwrrsg10xIuLrbSL09NSktMLim2Ss7PLcgvXsTK6ZSap-BWlF9cAgD4DUh4PgAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQmxN6BAgMEBY"
      }
    ],
    "created_by": "Baran bo Odar; Jantje Friese",
    "created_by_links": [
      {
        "text": "Baran bo Odar",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=Baran+bo+Odar&stick=H4sIAAAAAAAAAOPgE-LVT9c3NEwuNksvqciOV-LSz9U3SC5MMi420xItLrbSL09NSktMLim2Si5KTSyJT6pcxMrrlFiUmKeQlK_gn5JYBADRi_zQRAAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQmxN6BAgMEBg"
      },
      {
        "text": "Jantje Friese",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=Jantje+Friese&stick=H4sIAAAAAAAAAOPgE-LVT9c3NEwuNksvqciOV4Jw04zzkk0Kc_O0RIuLrfTLU5PSEpNLiq2Si1ITS-KTKhex8nol5pVkpSq4FWWmFqcCAE_czEFHAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQmxN6BAgMEBk"
      }
    ],
    "executive_producers": "Justyna Müsch; Jantje Friese; Quirin Berg; Max Wiedemann; Abraham Davies",
    "opening_theme": "\"Goodbye\" by Apparat (featuring Soap&Skin)",
    "opening_theme_links": [
      {
        "text": "\"Goodbye\" by Apparat (featuring Soap&Skin)",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=%22Goodbye%22+by+Apparat+(featuring+Soap%26Skin)&stick=H4sIAAAAAAAAAOPgE-LVT9c3NEwuNksvqciOV-LSz9U3MCyrNCk20hIvLrbSL09NSktMLim2yi9IzYsvyUjNTV3EqqXknp-fklSZqqSQVKngWFCQWJRYoqCRlppYUlqUmZeuEJyfWKAWnJ2ZpwkAK8prV2MAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQmxN6BAgMEBw"
      }
    ],
    "episodes": [
      {
        "name": "S03 E01 · Deja-vu",
        "extensions": [
          "Jun 27, 2020"
        ],
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=dark+season+3+episode+1&stick=H4sIAAAAAAAAAONgFmJQ4tVP1zc0TCu3KIw3tDTSkspOttIvKQOi-IKi_PSixFyr1ILM4vyU1OJFrOIpiUXZCsWpicX5eQrGClAJBUMAxQLlxUkAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQri56BAgMEB8",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=dark+season+3+episode+1"
      },
      {
        "name": "S03 E02 · The Survivors",
        "extensions": [
          "Jun 27, 2020"
        ],
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=dark+season+3+episode+2&stick=H4sIAAAAAAAAAONgFmJQ4tVP1zc0zCozT8-Jz8vRkspOttIvKQOi-IKi_PSixFyr1ILM4vyU1OJFrOIpiUXZCsWpicX5eQrGClAJBSMAysCNQUkAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQri56BAgMECE",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=dark+season+3+episode+2"
      },
      {
        "name": "S03 E03 · Adam and Eva",
        "extensions": [
          "Jun 27, 2020"
        ],
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=dark+season+3+episode+3&stick=H4sIAAAAAAAAAONgFmJQ4tVP1zc0zErJLTYqTMrSkspOttIvKQOi-IKi_PSixFyr1ILM4vyU1OJFrOIpiUXZCsWpicX5eQrGClAJBWMAEl22tUkAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQri56BAgMECM",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=dark+season+3+episode+3"
      },
      ...
    ],
    "cast": [
      {
        "name": "Louis Hofmann",
        "extensions": [
          "Jonas Kahnwald"
        ],
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTxn8quaLku17WBx86Ge3sV-IZdOx6DeUlv_ItrabpL1Xn77MD9zh7y9DE&s=0",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=Louis+Hofmann&stick=H4sIAAAAAAAAAONgFuLVT9c3NEwuNksvqciOV-LSz9U3yDKtzCi20BLLTrbSLykDoviCovz0osRcq-TE4pJFrLw--aWZxQoe-Wm5iXl5APhlimhFAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQ0I4BegQIDBBU",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=Louis+Hofmann"
      },
      {
        "name": "Lisa Vicari",
        "extensions": [
          "Martha Nielsen"
        ],
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTXb93Ja9qN-aEqKEZGq5cvhDGZQjbnWX_fAOhGmrzG43qK_LsP3SJPz9A&s=0",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=Lisa+Vicari&stick=H4sIAAAAAAAAAONgFuLVT9c3NEwuNksvqciOV-LSz9U3yDKtzCjK0hLLTrbSLykDoviCovz0osRcq-TE4pJFrNw-mcWJCmGZyYlFmQBl7k_pQwAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQ0I4BegQIDBBW",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=Lisa+Vicari"
      },
      {
        "name": "Gina Stiebitz",
        "extensions": [
          "Franziska Doppler"
        ],
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSG4YQAGqNEx0Ry3o7PMKpwWnA9TYk6LwJqE6TDZOBR62oACmXa4HnzwLc&s=0",
        "link": "https://www.google.com/search?sca_esv=8ae81ea246257316&hl=en&gl=us&gbv=1&q=Gina+Stiebitz&stick=H4sIAAAAAAAAAONgFuLVT9c3NEwuNksvqciOV-IGcY0Mc80tyyq0xLKTrfRLyoAovqAoP70oMdcqObG4ZBErr3tmXqJCcElmalJmSRUAR_p5X0YAAAA&sa=X&ved=2ahUKEwi0v9yr0YKGAxVPJ0QIHf9SAVUQ0I4BegQIDBBY",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=Gina+Stiebitz"
      },
      ...
    ]
  },
  ...
}
```

### [](https://serpapi.com/google-light-knowledge-graph#api-examples-results-for-best-rpg-games) Results for: `best rpg games`

GET

*    
```url
https://serpapi.com/search.json?q=best+rpg+games&engine=google_light
```

  

Code to integrate

cURL CLI Ruby Python JavaScript Go PHP Java Rust C++.NET Swift Google Sheets

*   [](https://github.com/serpapi/serpapi-ruby)[](https://rubygems.org/gems/serpapi) 
```ruby
require "serpapi" 

client = SerpApi::Client.new(
  q: "best rpg games",
  engine: "google_light",
  api_key: "secret_api_key"
)

results = client.search
knowledge_graph = results[:knowledge_graph]
```

  

JSON Example

[](https://serpapi.com/playground?q=best+rpg+games&engine=google_light&highlight=knowledge_graph)

```json
{
  ...
  "knowledge_graph": {
    "title": "Popular on the web",
    "popular_on_the_web": [
      {
        "name": "The Elder Scrolls V...",
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTy0Qskt39zUGaP4DDOpK65ab_Kkv8qOW9M7potR2hOh6hCYF5PIeLYbwk&s=0",
        "link": "https://www.google.com/search?sca_esv=16b87234c4719fc3&gl=us&gbv=1&hl=en&q=The+Elder+Scrolls+V:+Skyrim&stick=H4sIAAAAAAAAAE2TPW_TQBjH46itUregJl2qMmBFCEWVUHw-v8QdoAI6lkp9gdHE77HPr2c5PkssfAQGYGFhYgA-AANUSKiiAwMDAxIIMYEYkJgYECIBn4On-_t3z3P_53nuWvPdxX7Q50UnKD3htG7hjEtjh3OGgYVPmBk7YU71nT4ALixFTeAnmp0yP7cDNanhYOAQrBGq7ZDksYtcqhOYJXY2dqpgqdRUo4b6GBqYL9wKhrDgBbsSriTJPCVw7GLTqc9AaGB7BqnMCokR1MxARFJ9HZ4wS1MGoK0M9KDaCUSkitUaYh7Q9HrgQE_9LyRzc5rQT2CSI1Brl2SOmska1chJbOC5SpVKNEpDTSkkoHAC3yipU5dgndYHQ3Fs0I1mWRKSg8HMg1wmmCq-MJXYpnsd3jehVMq0azYMBnHdGw8KquIFFSzNuMzpVAUxReGsLieTwnFJdRCbCV94Up1IVjVfwCn1AHCIHXVGCUzk6eQqqgiarsyorPEImFRjqBJTNzHVXhgCXgX67B4ohSnxg3qIECkCUaXKt2TYOajWOsnGsK5BJlIminlVrIahq9WdMALDVlPRp7CQ1ML4zPxilla-_vy4uv6DufP49TvmG8POXZ68gY7NLu1b2UG0E5kjm3RudA7ZxR0r0K0U79odmWWvRAhZRjaKwk5v_Tx7rm_UP_pphKwLMRqSUeho-ci0Iu3ve-ou7_27FjxE0Nls9prdsXD47O3dNwu77cbke39rb2u9t9FmF65GwXAUtl8xT54WH75c3FhlWwfDIgqjgLRf3D8---De90vdtWnQzd-frm2tLXKNXgNMJLd9vHq00dir5khAJoIsPmKat58_ernQajErDaHZapTN1tzyw_kzB67FbSPTSrl9Y2IbYe76Jrfvk3QU_AEVOXoWGwQAAA&sa=X&ved=2ahUKEwiTsOSX1oyGAxVqJEQIHeQYDd4Q-BZ6BAgMEAI",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=The+Elder+Scrolls+V%3A+Skyrim"
      },
      {
        "name": "Elden Ring",
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSbuC_qNI8skc3ZcU0uweJMXhqyI041JqP7KNjVcAXsAZtbeLc7dWTvYQI&s=0",
        "link": "https://www.google.com/search?sca_esv=16b87234c4719fc3&gl=us&gbv=1&hl=en&q=Elden+Ring&stick=H4sIAAAAAAAAAFWTPW_TQBjH46itUrcgki5VF6IIoagSis_nlxwDVEDHUim0YjTx2zn2-S22HJ8lFj4CA7CwMDEAH4ABKiRUkYGBgQEJhJhADEhMDAiRgM8BT_f373me-z_33DWWOyd6uAeAAwtJEwVXPKlbSdoeR7iNh76VTLnVnt8TJOwX7pT7P3bK8XPmZbaP4gr2-5gmGmXaDmgWOcRhOoZpbKcTXCbLhYaMCuoTaCRC7pQwgLkg2qVwZFkRGIETJzFxtQchfds1aGlWjA2_YgahMvJ0OOXW5gxAW-3rfhkJJIKkcg0TAbDyuo-hi_5JSZ2MFfRiGGcEVNqhKUapojFNcGwD11HLUpJRGGjMIAU59j2jYE4dmuisPxhIE4MFmkVBaQb6Cw9KESdMCbmpRjaLxYJnQrlQ2KnZ0O9H1dm4UESq65ewMKMiY1MVpTEJFn3hVA4mBdN-ZMZC7spVIQVpnpiMmQeQBAlGC0phrMwnV1JV1HR1QRVNIMBkOoGImrqZMO0GARAQ0Bf3QM1NWehXQ4REFSmSS9-yYWegXOs0ncCqB4XKqSRlZbNaAh2tOgnDN2w0ljwGcxnlxifuJ7d26suPDxtb37nbj1695b5y_NKl2Rto2fzaNSs9CPdCc2TT1vXWIb-6Z_m6NU727ZbC85dDQiwjHYVBq7t1lj_TM6ofvXFIrHMRGdJRgLVsZFqh9uc9ddYHf6-FAAnE5-vdemciHj59c-f1yn6zNvve3RzsbHW3m_zKldAfjoLmS-7xk_z95wvbG3zjYJiHQejT5vN7x6fv3_12sbM5T7rx6-PVnc3Vdq1bAzPZ3j3eONquDco5UpBKII2OuPqtZw9frDQa3KmaWG_Uinpjaf3BMr9LTCtoD2ZGfwPMqSOEDgQAAA&sa=X&ved=2ahUKEwiTsOSX1oyGAxVqJEQIHeQYDd4Q-BZ6BAgMEAQ",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=Elden+Ring"
      },
      {
        "name": "Cyberpunk 2077",
        "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSfOfwHafQRkCbDr8hBLC4umA9-r1cp1RwXqFCImqU&s=0",
        "link": "https://www.google.com/search?sca_esv=16b87234c4719fc3&gl=us&gbv=1&hl=en&q=Cyberpunk+2077&stick=H4sIAAAAAAAAAE2TPW_TQBjH46itUrdUTbpUXYgihKJKKD6fX2IGqCiMpVJpxWjis32OfX6LXcdniYWPwAAsLEwMwAdggAoJVXRgYGBAAiEmEAMSEwNCJOBzetP97_c8zz0vd435Dt_ze4KX2b4WiyuGlaTtUYTbeOBbyQm3OIUS9gv3hDvTwz0AHFhIuihM9CnHCvb7mCY6ZdoOaBY5xGE6hmlsp2NcOsuFrqEKGmOIEiF3ShjAXBDtUjiyrAiMwLGTmLi6g5C-7SJaJivGyK8YIlTWPAOecEtTBqCt9g2_tAQS0aRyDxMBsPCGj6GrnXJJnYwF9GIYZwRU2qEp1lJFZ5rg2Aauo5ahJFQgbcQgBTn2PVSwTB2aGKw-GEhjxAzNoqA0A_1ZDkoRJ0wJualGNrPFgmdCuVBY12zo96OqNy4UNdX1S1iYUZGxqYrSiASzunAqB-OCaT8yYyF35SqQoumemIxYDiAJEqzNKIWxMp1cSVVRN9QZVXSBAJPpBGrUNMyEaTcIgKABY_YO1NyUhX41REhUkWpymbeM7AyUe4OmY1jVoFA5laSsLFZPoKNXnUA-srWR5DGYy1qOvnC_uaXVb78-rW385O4-efOe-87xc1cmf6Bl80s3rHQ_3AnNoU1bN1sH_OKO5RvWKNm1WwrPb4eEWCgdhkGru3GeP9dD1UFvFBLrQkQGdBhgPRuaVqj_-0-d5b3_z0KABOKL9W69MxYPnr-793Zht1mbrA-397Y2uptNfuFq6A-GQfM19_RZ_vHrpc01vrE_yMMg9Gnz5YPjsw_v_7jcWZ863frz-frW-mK71q2BiWxfO1472qztlXOkIJVAGh1x9TsvHr9aaDS41ZpYb9SKemNu-dH8yjadlBQdBl5bFFT1L-s77a0PBAAA&sa=X&ved=2ahUKEwiTsOSX1oyGAxVqJEQIHeQYDd4Q-BZ6BAgMEAY",
        "serpapi_link": "https://serpapi.com/search.json?device=desktop&engine=google_light&gl=us&google_domain=google.com&hl=en&q=Cyberpunk+2077"
      },
      ...
    ]
  }
  ...
}
```

### **SerpApi** results for ""

[×](javascript:void(0) "Clear search box")

Custom Search

Sort by

Relevance

Date