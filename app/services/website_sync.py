import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from app.config import get_settings
from app.services.ingestion import ingest_text

IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form"}
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "summary", "br"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class MainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.ignore_depth = 0
        self.title_depth = 0
        self.heading: str | None = None
        self.tag_ignores: list[bool] = []
        self.text: list[str] = []
        self.title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        low_value = any(term in f"{attributes.get('id', '')} {attributes.get('class', '')}".lower() for term in ("cookie", "banner", "breadcrumb", "navigation", "newsletter"))
        if tag == "main":
            self.main_depth = 1
        elif self.main_depth:
            self.main_depth += 1
        ignored_here = tag in IGNORED_TAGS or low_value
        if tag not in VOID_TAGS:
            self.tag_ignores.append(ignored_here)
        if ignored_here:
            self.ignore_depth += 1
        if tag == "title":
            self.title_depth += 1
        if self.main_depth and not self.ignore_depth and tag in BLOCK_TAGS:
            self.text.append("\n")
        if tag in {"h1", "h2", "h3", "h4"}:
            self.heading = tag
            self.text.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag: str) -> None:
        ignored_here = self.tag_ignores.pop() if self.tag_ignores else False
        if ignored_here and self.ignore_depth:
            self.ignore_depth -= 1
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if self.main_depth:
            self.main_depth -= 1
        if self.heading == tag:
            self.heading = None

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self.ignore_depth:
            return
        if self.title_depth:
            self.title.append(value)
        if self.main_depth:
            self.text.append(value)

    def result(self) -> tuple[str, str]:
        title = " ".join(self.title).strip() or "Truefox AI"
        content = "\n".join(line.strip() for line in " ".join(self.text).splitlines() if line.strip())
        content = re.sub(r"(?:GET STARTED|BOOK A DEMO|CONTACT US)\s*", "", content, flags=re.IGNORECASE)
        return title, content


def _allowed_base(base_url: str) -> str:
    settings = get_settings()
    parsed = urlparse(base_url)
    production_host = urlparse(settings.company_site_url).hostname
    local = parsed.hostname in {"localhost", "127.0.0.1"} and settings.app_env != "production"
    if parsed.scheme not in {"http", "https"} or (parsed.hostname != production_host and not local):
        raise ValueError("Website sync is restricted to the configured company website.")
    return base_url.rstrip("/")


def classify_path(path: str) -> tuple[str, str]:
    category = next((item for item in ("products", "services", "careers", "contact", "industries", "solutions") if item in path), "company")
    document_type = {"products": "product", "services": "service", "careers": "career", "contact": "contact"}.get(category, category)
    return document_type, category


async def sync_website(base_url: str | None = None) -> list[dict[str, object]]:
    root = _allowed_base(base_url or get_settings().company_site_url)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "TruefoxKnowledgeSync/1.0"}) as client:
        sitemap = await client.get(f"{root}/sitemap.xml")
        sitemap.raise_for_status()
        xml = ElementTree.fromstring(sitemap.content)
        locations = [node.text for node in xml.findall("{*}url/{*}loc") if node.text]
        results: list[dict[str, object]] = []
        seen_checksums: set[str] = set()
        for location in locations:
            path = urlparse(location).path or "/"
            if path.startswith("/admin"):
                continue
            url = urljoin(f"{root}/", path.lstrip("/"))
            response = await client.get(url)
            response.raise_for_status()
            parser = MainTextParser()
            parser.feed(response.text)
            title, content = parser.result()
            fingerprint = re.sub(r"\W+", "", content.lower())
            if len(content) < 80 or fingerprint in seen_checksums:
                continue
            seen_checksums.add(fingerprint)
            document_type, category = classify_path(path)
            metadata = {"path": path, "sync": "website", "document_type": document_type, "category": category, "source": url}
            results.append(await ingest_text(title=title, source=url, text=content, mime_type="text/html", metadata=metadata))
    return results
