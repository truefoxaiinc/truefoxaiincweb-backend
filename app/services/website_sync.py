from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from app.config import get_settings
from app.services.ingestion import ingest_text


class MainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.ignored = 0
        self.title_depth = 0
        self.text: list[str] = []
        self.title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "main" or self.depth: self.depth += 1
        if tag in {"script", "style", "noscript", "svg"}: self.ignored += 1
        if tag == "title": self.title_depth += 1
        if self.depth and tag in {"h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "summary", "br"}: self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.ignored: self.ignored -= 1
        if tag == "title" and self.title_depth: self.title_depth -= 1
        if self.depth: self.depth -= 1

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self.ignored: return
        if self.title_depth: self.title.append(value)
        if self.depth: self.text.append(value)

    def result(self) -> tuple[str, str]:
        title = " ".join(self.title).strip() or "Truefox AI"
        content = "\n".join(line.strip() for line in " ".join(self.text).splitlines() if line.strip())
        return title, content


def _allowed_base(base_url: str) -> str:
    settings = get_settings()
    parsed = urlparse(base_url)
    production_host = urlparse(settings.company_site_url).hostname
    local = parsed.hostname in {"localhost", "127.0.0.1"} and settings.app_env != "production"
    if parsed.scheme not in {"http", "https"} or (parsed.hostname != production_host and not local):
        raise ValueError("Website sync is restricted to the configured company website.")
    return base_url.rstrip("/")


async def sync_website(base_url: str | None = None) -> list[dict[str, object]]:
    root = _allowed_base(base_url or get_settings().company_site_url)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "TruefoxKnowledgeSync/1.0"}) as client:
        sitemap = await client.get(f"{root}/sitemap.xml")
        sitemap.raise_for_status()
        xml = ElementTree.fromstring(sitemap.content)
        locations = [node.text for node in xml.findall("{*}url/{*}loc") if node.text]
        results: list[dict[str, object]] = []
        for location in locations:
            path = urlparse(location).path or "/"
            if path.startswith("/admin"): continue
            url = urljoin(f"{root}/", path.lstrip("/"))
            response = await client.get(url)
            response.raise_for_status()
            parser = MainTextParser()
            parser.feed(response.text)
            title, content = parser.result()
            if len(content) < 40: continue
            results.append(await ingest_text(title=title, source=url, text=content, mime_type="text/html", metadata={"path": path, "sync": "website"}))
    return results
