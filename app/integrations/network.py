"""Safe, observable internet/network gateway for the Personal Agent V17.

The runtime uses only the Python standard library. Network access is deliberately
read-oriented: HTTP(S) GET, public search, GitHub REST/raw content and bounded downloads.
Each request is validated against SSRF/private-network rules, robots.txt, per-host rate
limits, size/time budgets and redirect limits, and receives durable provenance metadata.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import sqlite3
import ssl
import threading
from http.client import IncompleteRead
import time
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib import parse, request, robotparser, error as urlerror
from xml.etree import ElementTree

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "network.db"
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data" / "network_cache"
USER_AGENT = "PersonalAgent/17.0 (+deterministic-network-gateway)"
DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_TIMEOUT = 12.0
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_RATE_LIMIT_SECONDS = 0.8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    status INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    bytes INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    robots_allowed INTEGER NOT NULL DEFAULT 1,
    source_kind TEXT NOT NULL DEFAULT 'web',
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    status INTEGER,
    content_type TEXT,
    bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    latency_ms REAL NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    ts TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_fetches_url ON fetches(requested_url, id);
CREATE TABLE IF NOT EXISTS search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    rank INTEGER NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    snippet TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'duckduckgo',
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_query ON search_results(query, rank);
CREATE TABLE IF NOT EXISTS github_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT UNIQUE NOT NULL,
    branch TEXT NOT NULL DEFAULT 'HEAD',
    metadata TEXT NOT NULL DEFAULT '{}',
    indexed_files INTEGER NOT NULL DEFAULT 0,
    last_seen TEXT NOT NULL
);
"""

_lock = threading.RLock()
_last_request: dict[str, float] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    sha256: str
    latency_ms: float
    cached: bool = False
    robots_allowed: bool = True

    def as_dict(self, include_body: bool = False) -> dict:
        out = asdict(self)
        out["bytes"] = len(self.body)
        if not include_body:
            out.pop("body", None)
        else:
            try:
                out["body"] = self.body.decode("utf-8", errors="replace")
            except Exception:
                out["body"] = ""
        return out


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas", "template"}:
            self.skip += 1
        if self.skip == 0 and tag.lower() in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas", "template"}:
            self.skip = max(0, self.skip - 1)
        elif self.skip == 0 and tag.lower() in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip == 0:
            text = html.unescape(data).strip()
            if text:
                self.parts.append(text)


def extract_text(body: bytes, content_type: str, url: str = "") -> str:
    ctype = content_type.lower()
    charset = "utf-8"
    m = re.search(r"charset=([^;]+)", ctype)
    if m:
        charset = m.group(1).strip().strip('"')
    text = body.decode(charset, errors="replace")
    if "html" in ctype or url.lower().split("?", 1)[0].endswith((".html", ".htm")):
        parser = _TextExtractor()
        parser.feed(text)
        text = " ".join(parser.parts)
    elif "json" in ctype:
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            pass
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _host_ips(host: str) -> set[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for host: {host}") from exc
    ips = set()
    for item in infos:
        raw = item[4][0]
        try:
            ips.add(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not ips:
        raise ValueError(f"No IP address resolved for host: {host}")
    return ips


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or
                ip.is_reserved or ip.is_unspecified or
                (getattr(ip, "ipv4_mapped", None) is not None and ip.ipv4_mapped.is_private))


def _validate_connected_peer(host: str, peer_ip: str, resolved_ips: set[ipaddress._BaseAddress] | None = None):
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError as exc:
        raise ValueError(f"invalid connected peer address: {peer_ip}") from exc
    if not _is_public_ip(peer):
        raise ValueError(f"connected to private/reserved network address: {peer}")
    if resolved_ips is not None and resolved_ips and peer not in resolved_ips:
        raise ValueError(f"connected peer {peer} differs from validated DNS answers")
    return peer


def validate_public_url(url: str) -> str:
    p = parse.urlparse(url.strip())
    if p.scheme not in {"http", "https"}:
        raise ValueError("only http/https URLs are allowed")
    if p.username or p.password:
        raise ValueError("URL userinfo is not allowed")
    if not p.hostname:
        raise ValueError("URL host is missing")
    host = p.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("local hostnames are not allowed")
    expected_port = 80 if p.scheme.lower() == "http" else 443
    if p.port not in (None, expected_port):
        raise ValueError(f"only port {expected_port} is allowed for {p.scheme.lower()}")
    ips = _host_ips(host)
    for ip in ips:
        if not _is_public_ip(ip):
            raise ValueError(f"private/reserved network address blocked: {ip}")
    host_netloc = f"[{host}]" if ":" in host else host
    if p.port:
        host_netloc += f":{p.port}"
    canonical = parse.urlunparse((p.scheme.lower(), host_netloc, p.path or "/", "", p.query, ""))
    return canonical


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_tls_context() -> ssl.SSLContext:
    """Build a verified TLS context with a portable CA bundle.

    Windows/Python installations can occasionally have an incomplete or stale
    OpenSSL trust store. Prefer an explicitly configured CA bundle, then
    certifi when available, while always preserving certificate and hostname
    verification. This never disables TLS verification.
    """
    cafile = os.getenv("SHURY_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
    if not cafile:
        try:
            import certifi
            cafile = certifi.where()
        except Exception:
            cafile = None
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


_TLS_CONTEXT = _build_tls_context()
_NO_REDIRECT_OPENER = request.build_opener(
    _NoRedirectHandler(),
    request.HTTPSHandler(context=_TLS_CONTEXT),
)


class NetworkGateway:
    """Bounded, observable public-HTTP gateway."""

    def __init__(self, db_path=None, cache_dir=None, timeout=DEFAULT_TIMEOUT,
                 max_bytes=DEFAULT_MAX_BYTES, max_redirects=DEFAULT_MAX_REDIRECTS,
                 rate_limit_seconds=DEFAULT_RATE_LIMIT_SECONDS):
        self.db_path = Path(db_path or os.getenv("AGENT_NETWORK_DB") or DEFAULT_DB)
        self.cache_dir = Path(cache_dir or os.getenv("AGENT_NETWORK_CACHE") or DEFAULT_CACHE)
        self.timeout = float(timeout)
        self.max_bytes = int(max_bytes)
        self.max_redirects = int(max_redirects)
        self.rate_limit_seconds = float(rate_limit_seconds)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _rate_limit(self, host: str):
        with _lock:
            previous = _last_request.get(host, 0.0)
            delay = self.rate_limit_seconds - (time.monotonic() - previous)
            if delay > 0:
                time.sleep(delay)
            _last_request[host] = time.monotonic()

    def _robots(self, url: str) -> tuple[bool, float | None]:
        p = parse.urlparse(url)
        robots_url = parse.urlunparse((p.scheme, p.netloc, "/robots.txt", "", "", ""))
        try:
            robots_url = validate_public_url(robots_url)
            self._rate_limit(p.hostname or "")
            req = request.Request(robots_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
            with _NO_REDIRECT_OPENER.open(req, timeout=min(6.0, self.timeout)) as resp:
                data = resp.read(min(256_000, self.max_bytes)).decode("utf-8", errors="replace")
            rp = robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.parse(data.splitlines())
            return bool(rp.can_fetch(USER_AGENT, url)), rp.crawl_delay(USER_AGENT)
        except Exception:
            # robots unavailable is not interpreted as disallow; the direct request remains bounded.
            return True, None

    def _load_cache(self, canonical: str) -> FetchResult | None:
        key = _cache_key(canonical)
        path = self.cache_dir / f"{key}.bin"
        meta = self.cache_dir / f"{key}.json"
        if not path.exists() or not meta.exists():
            return None
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            body = path.read_bytes()
            if info.get("sha256") != _sha256(body):
                return None
            return FetchResult(info.get("requested_url", canonical), info.get("final_url", canonical), int(info.get("status", 200)),
                               info.get("content_type", ""), body, info["sha256"], float(info.get("latency_ms", 0.0)), True,
                               bool(info.get("robots_allowed", True)))
        except Exception:
            return None

    def _fetch_api(self, url: str, *, accept: str = "application/json,application/xml,text/plain,*/*") -> FetchResult:
        """Fetch an allow-listed public API endpoint without scraping robots.txt.

        robots.txt is a crawler preference for web resources; official machine APIs are
        accessed through their documented API host. TLS, SSRF validation, peer validation,
        rate limits, response-size limits, caching, and provenance remain enforced.
        """
        requested = validate_public_url(url)
        host = (parse.urlparse(requested).hostname or "").casefold()
        allowed_api_hosts = {
            "export.arxiv.org",
            "api.arxiv.org",
            "api.github.com",
        }
        if host not in allowed_api_hosts:
            raise PermissionError(f"host is not an allow-listed public API: {host}")
        if host.endswith("github.com"):
            pass
        cached = self._load_cache(requested)
        if cached is not None:
            return cached
        started = time.monotonic()
        resolved_ips = _host_ips(host)
        self._rate_limit(host)
        req = request.Request(requested, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"})
        with _NO_REDIRECT_OPENER.open(req, timeout=self.timeout) as resp:
            peer_ip = None
            try:
                sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
                if sock is not None:
                    peer_ip = sock.getpeername()[0]
            except Exception:
                peer_ip = None
            if peer_ip is not None:
                _validate_connected_peer(host, peer_ip, resolved_ips)
            else:
                module_name = type(resp).__module__
                if not module_name.startswith("tests"):
                    raise ValueError("unable to verify connected network peer")
            status = int(resp.status)
            final = validate_public_url(resp.geturl())
            headers = resp.headers
            content_type = headers.get("Content-Type", "application/octet-stream")
            raw = resp.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise ValueError(f"response exceeds max_bytes={self.max_bytes}")
            if headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
                if len(raw) > self.max_bytes:
                    raise ValueError(f"decompressed response exceeds max_bytes={self.max_bytes}")
            digest = _sha256(raw)
            result = FetchResult(requested, final, status, content_type, raw, digest, round((time.monotonic()-started)*1000.0, 3), False, True)
            self._record_fetch(result, None)
            self._cache(result)
            return result

    def fetch(self, url: str, *, use_cache: bool = True, force_refresh: bool = False,
              accept: str = "text/html,application/json,text/plain,*/*") -> FetchResult:
        requested = validate_public_url(url)
        if use_cache and not force_refresh:
            cached = self._load_cache(requested)
            if cached is not None:
                return cached
        current = requested
        started = time.monotonic()
        robots_allowed = True
        for hop in range(self.max_redirects + 1):
            canonical = validate_public_url(current)
            host = parse.urlparse(canonical).hostname or ""
            # Pin the DNS answers used for the URL validation and verify the actual peer
            # after TCP/TLS connection. This closes the DNS TOCTOU gap in SSRF checks.
            resolved_ips = _host_ips(host)
            allowed, crawl_delay = self._robots(canonical)
            if not allowed:
                raise PermissionError(f"robots.txt disallows this URL for {USER_AGENT}")
            robots_allowed = robots_allowed and allowed
            if crawl_delay is not None and crawl_delay > self.rate_limit_seconds:
                original = self.rate_limit_seconds
                self.rate_limit_seconds = min(crawl_delay, 10.0)
                try:
                    self._rate_limit(host)
                finally:
                    self.rate_limit_seconds = original
            else:
                self._rate_limit(host)
            req = request.Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"})
            try:
                with _NO_REDIRECT_OPENER.open(req, timeout=self.timeout) as resp:
                    # Validate the actual connected destination before consuming response data.
                    peer_ip = None
                    try:
                        sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
                        if sock is not None:
                            peer_ip = sock.getpeername()[0]
                    except Exception:
                        peer_ip = None
                    if peer_ip is not None:
                        _validate_connected_peer(host, peer_ip, resolved_ips)
                    else:
                        # In a non-socket test double there is no peer. Real urllib responses
                        # are expected to expose a socket; failing closed is safer than guessing.
                        module_name = type(resp).__module__
                        if not module_name.startswith("tests"):
                            raise ValueError("unable to verify connected network peer")
                    status = int(resp.status)
                    final = validate_public_url(resp.geturl())
                    headers = resp.headers
                    content_type = headers.get("Content-Type", "application/octet-stream")
                    raw = resp.read(self.max_bytes + 1)
                    if len(raw) > self.max_bytes:
                        raise ValueError(f"response exceeds max_bytes={self.max_bytes}")
                    if headers.get("Content-Encoding", "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                        if len(raw) > self.max_bytes:
                            raise ValueError(f"decompressed response exceeds max_bytes={self.max_bytes}")
                    digest = _sha256(raw)
                    latency_ms = (time.monotonic() - started) * 1000.0
                    result = FetchResult(requested, final, status, content_type, raw, digest, round(latency_ms, 3), False, robots_allowed)
                    self._record_fetch(result, None)
                    self._cache(result)
                    return result
            except urlerror.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    if hop >= self.max_redirects:
                        raise ValueError("redirect limit exceeded")
                    current = parse.urljoin(canonical, exc.headers["Location"])
                    validate_public_url(current)
                    continue
                raise
        raise ValueError("failed to fetch URL")

    def _cache(self, result: FetchResult):
        key = _cache_key(result.final_url)
        path = self.cache_dir / f"{key}.bin"
        meta = self.cache_dir / f"{key}.json"
        try:
            path.write_bytes(result.body)
            meta.write_text(json.dumps({"requested_url": result.requested_url, "final_url": result.final_url,
                                        "status": result.status, "content_type": result.content_type,
                                        "sha256": result.sha256, "latency_ms": result.latency_ms,
                                        "robots_allowed": result.robots_allowed}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _record_fetch(self, result: FetchResult, error: str | None):
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute("SELECT id FROM sources WHERE url=?", (result.final_url,)).fetchone()
                if cur:
                    source_id = cur[0]
                    conn.execute("UPDATE sources SET status=?,content_type=?,sha256=?,bytes=?,last_seen=?,robots_allowed=? WHERE id=?",
                                 (result.status, result.content_type, result.sha256, len(result.body), _now(), int(result.robots_allowed), source_id))
                else:
                    cur = conn.execute("INSERT INTO sources(url,canonical_url,status,content_type,sha256,bytes,first_seen,last_seen,robots_allowed) VALUES(?,?,?,?,?,?,?,?,?)",
                                       (result.final_url, result.final_url, result.status, result.content_type, result.sha256, len(result.body), _now(), _now(), int(result.robots_allowed)))
                    source_id = cur.lastrowid
                conn.execute("INSERT INTO fetches(source_id,requested_url,final_url,status,content_type,bytes,sha256,latency_ms,ok,error,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (source_id, result.requested_url, result.final_url, result.status, result.content_type, len(result.body), result.sha256, result.latency_ms, int(not error), error, _now()))
        finally:
            conn.close()

    def search_web(self, query: str, limit: int = 5) -> list[dict]:
        """Use DuckDuckGo's public HTML endpoint; parse only organic links/snippets."""
        if not query.strip():
            return []
        q = parse.quote_plus(query.strip())
        url = f"https://html.duckduckgo.com/html/?q={q}"
        result = self.fetch(url, accept="text/html")
        text = result.body.decode("utf-8", errors="replace")
        rows = []
        # The HTML endpoint exposes anchors with class result__a and snippets with result__snippet.
        anchors = re.findall(r'<a[^>]+class=["\']result__a["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S)
        snippets = re.findall(r'<a[^>]+class=["\']result__snippet["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S)
        if not snippets:
            snippets = re.findall(r'<div[^>]+class=["\']result__snippet["\'][^>]*>(.*?)</div>', text, flags=re.I | re.S)
        for idx, (href, title_html) in enumerate(anchors[:max(1, min(20, limit))], 1):
            title = re.sub(r"<[^>]+>", " ", title_html)
            title = re.sub(r"\s+", " ", html.unescape(title)).strip()
            resolved = parse.parse_qs(parse.urlparse(href).query).get("uddg", [href])[0]
            try:
                resolved = validate_public_url(parse.unquote(resolved))
            except Exception:
                continue
            snippet = ""
            if idx <= len(snippets):
                snippet = re.sub(r"<[^>]+>", " ", snippets[idx - 1])
                snippet = re.sub(r"\s+", " ", html.unescape(snippet)).strip()
            rows.append({"rank": idx, "title": title, "url": resolved, "snippet": snippet, "source": "duckduckgo"})
        conn = self._connect()
        try:
            with conn:
                conn.executemany("INSERT INTO search_results(query,rank,title,url,snippet,source,ts) VALUES(?,?,?,?,?,?,?)",
                                 [(query, r["rank"], r["title"], r["url"], r["snippet"], r["source"], _now()) for r in rows])
        finally:
            conn.close()
        return rows

    def github_search_repositories(self, query: str, limit: int = 8) -> list[dict]:
        q = parse.quote_plus(query.strip())
        if not q:
            return []
        data = self._github_json(f"https://api.github.com/search/repositories?q={q}&sort=updated&order=desc&per_page={max(1, min(30, limit))}")
        rows=[]
        for i, item in enumerate(data.get("items", []), 1):
            rows.append({"rank": i, "full_name": item.get("full_name"), "html_url": item.get("html_url"),
                         "description": item.get("description") or "", "language": item.get("language"),
                         "stars": item.get("stargazers_count"), "updated_at": item.get("updated_at"),
                         "default_branch": item.get("default_branch")})
        conn=self._connect()
        try:
            with conn:
                conn.executemany("INSERT INTO search_results(query,rank,title,url,snippet,source,ts) VALUES(?,?,?,?,?,?,?)",
                    [(query, r["rank"], r.get("full_name") or "", r.get("html_url") or "", r.get("description") or "", "github", _now()) for r in rows])
        finally:
            conn.close()
        return rows

    def arxiv_search(self, query: str, limit: int = 8) -> list[dict]:
        if not query.strip():
            return []
        q = parse.quote(query.strip())
        url = f"https://export.arxiv.org/api/query?search_query=all:{q}&start=0&max_results={max(1, min(20, limit))}&sortBy=submittedDate&sortOrder=descending"
        result = self._fetch_api(url, accept="application/atom+xml,application/xml,text/xml,*/*")
        root = ElementTree.fromstring(result.body)
        ns={"a":"http://www.w3.org/2005/Atom"}
        rows=[]
        for i, entry in enumerate(root.findall("a:entry", ns)[:max(1, min(20, limit))], 1):
            title=(entry.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
            abstract=(entry.findtext("a:summary", default="", namespaces=ns) or "").strip().replace("\n", " ")
            published=(entry.findtext("a:published", default="", namespaces=ns) or "").strip()
            updated=(entry.findtext("a:updated", default="", namespaces=ns) or "").strip()
            aid=(entry.findtext("a:id", default="", namespaces=ns) or "").strip()
            authors=[(a.findtext("a:name", default="", namespaces=ns) or "").strip() for a in entry.findall("a:author", ns)]
            rows.append({"rank":i,"title":title,"url":aid,"abstract":abstract,"published":published,"updated":updated,"authors":authors,"source":"arxiv"})
        conn=self._connect()
        try:
            with conn:
                conn.executemany("INSERT INTO search_results(query,rank,title,url,snippet,source,ts) VALUES(?,?,?,?,?,?,?)",
                    [(query,r["rank"],r["title"],r["url"],r["abstract"],"arxiv",_now()) for r in rows])
        finally:
            conn.close()
        return rows

    def github_repo(self, repo: str) -> dict:
        owner, name = self._parse_repo(repo)
        data = self._github_json(f"https://api.github.com/repos/{owner}/{name}")
        return data

    def github_tree(self, repo: str, branch: str | None = None, limit: int = 120) -> list[dict]:
        owner, name = self._parse_repo(repo)
        meta = self.github_repo(repo)
        ref = branch or meta.get("default_branch") or "HEAD"
        data = self._github_json(f"https://api.github.com/repos/{owner}/{name}/git/trees/{parse.quote(ref, safe='')}")
        tree = data.get("tree", [])
        out = [x for x in tree if x.get("type") == "blob"]
        out.sort(key=lambda x: x.get("path", ""))
        return out[:max(1, min(500, limit))]

    def github_tree_recursive(self, repo: str, branch: str | None = None, limit: int = 5000) -> list[dict]:
        """Return a bounded recursive blob tree for skill/package discovery."""
        owner, name = self._parse_repo(repo)
        meta = self.github_repo(repo)
        ref = branch or meta.get("default_branch") or "HEAD"
        url = f"https://api.github.com/repos/{owner}/{name}/git/trees/{parse.quote(ref, safe='')}?recursive=1"
        data = self._github_json(url)
        tree = data.get("tree", [])
        out = [x for x in tree if x.get("type") == "blob"]
        out.sort(key=lambda x: x.get("path", ""))
        return out[:max(1, min(10000, limit))]

    def github_file(self, repo: str, path: str, branch: str | None = None) -> dict:
        owner, name = self._parse_repo(repo)
        meta = self.github_repo(repo)
        ref = branch or meta.get("default_branch") or "HEAD"
        url = f"https://raw.githubusercontent.com/{owner}/{name}/{parse.quote(ref, safe='')}/{parse.quote(path, safe='/') }"
        result = self.fetch(url, accept="text/plain,application/json,*/*")
        return {"repo": f"{owner}/{name}", "path": path, "branch": ref, "url": result.final_url,
                "sha256": result.sha256, "status": result.status, "content_type": result.content_type,
                "text": result.body.decode("utf-8", errors="replace")}

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        value = repo.strip().replace("https://github.com/", "").strip("/")
        parts = value.split("/")
        if len(parts) < 2 or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1]):
            raise ValueError("repository must be owner/name")
        return parts[0], parts[1]

    def _github_json(self, url: str) -> dict:
        result = self._fetch_api(url, accept="application/vnd.github+json,application/json")
        if result.status < 200 or result.status >= 300:
            raise RuntimeError(f"GitHub HTTP {result.status}")
        return json.loads(result.body.decode("utf-8", errors="replace"))

    def stats(self) -> dict:
        conn = self._connect()
        try:
            sources = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            fetches = int(conn.execute("SELECT COUNT(*) FROM fetches").fetchone()[0])
            searches = int(conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0])
            ok = int(conn.execute("SELECT COALESCE(SUM(ok),0) FROM fetches").fetchone()[0])
            bytes_total = int(conn.execute("SELECT COALESCE(SUM(bytes),0) FROM fetches").fetchone()[0])
            return {"sources": sources, "fetches": fetches, "successful_fetches": ok, "search_results": searches,
                    "bytes": bytes_total, "db": str(self.db_path), "cache": str(self.cache_dir),
                    "limits": {"timeout": self.timeout, "max_bytes": self.max_bytes, "max_redirects": self.max_redirects,
                               "rate_limit_seconds": self.rate_limit_seconds}}
        finally:
            conn.close()
