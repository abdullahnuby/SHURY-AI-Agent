# SHURY Network Research Policy

- Normal web fetching remains governed by TLS validation, SSRF checks, response limits, rate limits, and robots.txt policy.
- Paper-focused research uses the official arXiv API instead of scraping a search-engine HTML page.
- Official API hosts are accessed through a dedicated API fetch path with TLS/SSRF/peer validation still enforced.
- A robots denial or temporary failure from an optional provider is isolated and does not abort otherwise valid research evidence.
- No `verify=False`, certificate bypass, robots bypass for ordinary web pages, or arbitrary-domain API exemption is used.
