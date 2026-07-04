from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import argparse
import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "venues.json"
CACHE_PATH = ROOT / "data" / "exhibitions.json"
EVENT_CACHE_PATH = ROOT / "data" / "events.json"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
USER_AGENT = BROWSER_USER_AGENT
MAX_DETAIL_PAGES = 14
MAX_EVENT_DETAIL_PAGES = 36
REQUEST_TIMEOUT = 18
REQUEST_DELAY = 0.2
RETRY_DELAY = 1.5
EVENT_TIMEZONE = "America/New_York"

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "oktober": 10,
    "dezember": 12,
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}
MONTH_LABELS = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

MONTH_RE = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|"
    r"Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Setiembre|Octubre|Noviembre|Diciembre|"
    r"Januar|Februar|März|Maerz|Mai|Juni|Juli|Oktober|Dezember|"
    r"Января|Январь|Февраля|Февраль|Марта|Март|Апреля|Апрель|Мая|Май|Июня|Июнь|Июля|Июль|"
    r"Августа|Август|Сентября|Сентябрь|Октября|Октябрь|Ноября|Ноябрь|Декабря|Декабрь"
)
DATE_MENTION_RE = re.compile(
    rf"\b(?P<month>{MONTH_RE})(?=\.?\b)\.?\s+(?P<day>\d{{1,2}}(?!\d))?(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{{4}}))?",
    re.IGNORECASE,
)
DAY_MONTH_MENTION_RE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:\s+de)?\s+(?P<month>{MONTH_RE})(?=\.?\b)\.?(?:(?:\s+de)?(?:,?\s+)(?P<year>\d{{4}}))?",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
ISO_DATE_RE = re.compile(r"\b(20\d{2}|19\d{2})-\d{2}-\d{2}(?=\b|T)")
NUMERIC_DOT_DATE_RE = re.compile(r"\b(?P<month>\d{1,2})\.(?P<day>\d{1,2})\.(?P<year>\d{2,4})\b")
NUMERIC_DOT_RANGE_RE = re.compile(
    r"\b(?P<day1>\d{1,2})\.(?P<month1>\d{1,2})\.?\s*[-–—]\s*"
    r"(?P<day2>\d{1,2})\.(?P<month2>\d{1,2})\.(?P<year>\d{2,4})\b"
)
GLOBAL_EXCLUDE_URL_KEYWORDS = [
    "/archive",
    "/archives",
    "/browse/past",
    "/past",
    "/previous",
    "/traveling",
    "/digital",
    "/collection/",
]


@dataclass
class Link:
    href: str
    text: str


@dataclass
class ParsedPage:
    url: str
    raw_html: str = ""
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    headings: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    json_ld: list[str] = field(default_factory=list)

    @property
    def visible_text(self) -> str:
        return "\n".join(self.chunks[:650])


class PageParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page = ParsedPage(page_url)
        self._tag_stack: list[str] = []
        self._capture_title = False
        self._capture_script = False
        self._script_type = ""
        self._script_parts: list[str] = []
        self._current_link: dict[str, Any] | None = None
        self._text_tag = ""
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        self._tag_stack.append(tag)

        if tag == "title":
            self._capture_title = True
        elif tag == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name")
            content = attrs_dict.get("content", "")
            if key and content:
                self.page.meta[key.lower()] = clean_text(content)
        elif tag == "a" and attrs_dict.get("href"):
            self._current_link = {"href": attrs_dict["href"], "parts": []}
        elif tag == "img":
            src = image_from_img_attrs(attrs_dict, self.page.url)
            if src:
                self.page.images.append(src)
        if attrs_dict.get("style"):
            self.page.images.extend(image_urls_from_style(attrs_dict["style"], self.page.url))
        elif tag == "script":
            self._script_type = attrs_dict.get("type", "").lower()
            if "ld+json" in self._script_type:
                self._capture_script = True
                self._script_parts = []

        if tag in {"h1", "h2", "h3", "p", "li", "figcaption", "time"}:
            self._text_tag = tag
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self.page.title += data
        if self._capture_script:
            self._script_parts.append(data)
        if self._current_link is not None:
            self._current_link["parts"].append(data)
        if self._text_tag:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._capture_title = False
            self.page.title = clean_title(self.page.title)
        elif tag == "script" and self._capture_script:
            script = "".join(self._script_parts).strip()
            if script:
                self.page.json_ld.append(script)
            self._capture_script = False
            self._script_parts = []
        elif tag == "a" and self._current_link is not None:
            text = clean_text(" ".join(self._current_link["parts"]))
            if text:
                self.page.links.append(Link(self._current_link["href"], text))
            self._current_link = None

        if tag == self._text_tag:
            text = clean_text(" ".join(self._text_parts))
            if text:
                self.page.chunks.append(text)
                if tag in {"h1", "h2", "h3"}:
                    self.page.headings.append(text)
            self._text_tag = ""
            self._text_parts = []

        if self._tag_stack:
            self._tag_stack.pop()


def ensure_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        with CACHE_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    config = read_config()
    empty = {
        "generated_at": None,
        "cities": configured_cities(config),
        "tabs": config.get("tabs", []),
        "exhibitions": [],
        "errors": [],
    }
    write_cache(empty)
    return empty


def ensure_event_cache() -> dict[str, Any]:
    if EVENT_CACHE_PATH.exists():
        with EVENT_CACHE_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    config = read_config()
    empty = {
        "generated_at": None,
        "cities": configured_cities(config),
        "timezone": EVENT_TIMEZONE,
        "filters": ["Tours", "Talks", "Performances", "Family", "Free"],
        "events": [],
        "errors": [],
    }
    write_event_cache(empty)
    return empty


def write_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def write_event_cache(payload: dict[str, Any]) -> None:
    EVENT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def run_scrape() -> dict[str, Any]:
    config = read_config()
    previous_payload = ensure_cache()
    exhibitions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    tab_order = {tab: index for index, tab in enumerate(config.get("tabs", []))}
    for venue_order, venue_config in enumerate(config["venues"]):
        venue = {
            **venue_config,
            "venue_order": venue_order,
            "tab_order": tab_order.get(venue_config.get("tab", ""), 999),
        }
        try:
            time.sleep(REQUEST_DELAY)
            venue_items = scrape_venue(venue)
            exhibitions.extend(venue_items)
            print(f"{venue['name']}: {len(venue_items)} exhibitions", file=sys.stderr)
        except Exception as exc:
            fallback_items = cached_venue_items(previous_payload, venue)
            exhibitions.extend(fallback_items)
            errors.append(
                {
                    "venue": venue["name"],
                    "url": venue["url"],
                    "error": str(exc),
                    "preserved_cached_items": str(len(fallback_items)),
                }
            )
            print(f"{venue['name']}: ERROR {exc}; preserved {len(fallback_items)} cached items", file=sys.stderr)

    exhibitions = [
        item
        for item in dedupe_exhibitions(exhibitions)
        if item.get("status") in {"current", "upcoming"}
        and has_displayable_date(item)
        and not is_bad_title(item.get("title", ""), item.get("venue", ""))
    ]
    exhibitions.sort(key=sort_key)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cities": configured_cities(config),
        "tabs": config.get("tabs", []),
        "exhibitions": exhibitions,
        "errors": errors,
    }
    write_cache(payload)
    return payload


def run_all_scrapes() -> dict[str, Any]:
    exhibition_payload = run_scrape()
    event_payload = run_event_scrape()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exhibitions": exhibition_payload,
        "events": event_payload,
    }


def run_event_scrape() -> dict[str, Any]:
    config = read_config()
    previous_payload = ensure_event_cache()
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for venue_order, source_config in enumerate(config.get("event_sources", [])):
        if source_config.get("enabled", True) is False:
            continue
        source = {**source_config, "venue_order": venue_order}
        try:
            time.sleep(REQUEST_DELAY)
            venue_events = scrape_event_source(source)
            events.extend(venue_events)
            print(f"{source['name']}: {len(venue_events)} events", file=sys.stderr)
        except Exception as exc:
            fallback_items = cached_event_source_items(previous_payload, source)
            events.extend(fallback_items)
            errors.append(
                {
                    "venue": source["name"],
                    "url": source["url"],
                    "error": str(exc),
                    "preserved_cached_items": str(len(fallback_items)),
                }
            )
            print(f"{source['name']}: ERROR {exc}; preserved {len(fallback_items)} cached events", file=sys.stderr)

    events = [item for item in dedupe_events(events) if is_displayable_event(item)]
    events.sort(key=event_sort_key)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cities": configured_cities(config),
        "timezone": EVENT_TIMEZONE,
        "filters": ["Tours", "Talks", "Performances", "Family", "Free"],
        "events": events,
        "errors": errors,
    }
    write_event_cache(payload)
    return payload


def cached_venue_items(payload: dict[str, Any], venue: dict[str, Any]) -> list[dict[str, Any]]:
    cached_items = payload.get("exhibitions", [])
    if not isinstance(cached_items, list):
        return []
    return [
        copy.deepcopy(item)
        for item in cached_items
        if isinstance(item, dict)
        and item.get("venue") == venue.get("name")
        and item.get("city") == venue.get("city")
        and item.get("tab") == venue.get("tab")
    ]


def cached_event_source_items(payload: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    cached_items = payload.get("events", [])
    if not isinstance(cached_items, list):
        return []
    return [
        copy.deepcopy(item)
        for item in cached_items
        if isinstance(item, dict)
        and item.get("venue") == source.get("name")
        and item.get("city") == source.get("city")
    ]


def read_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def configured_cities(config: dict[str, Any]) -> list[str]:
    cities: list[str] = []
    for city in [*config.get("cities", []), *(venue.get("city") for venue in config.get("venues", []))]:
        if city and city not in cities:
            cities.append(city)
    return cities or ["NYC"]


def scrape_venue(venue: dict[str, Any]) -> list[dict[str, Any]]:
    listing = fetch_page(venue["url"])
    items: list[dict[str, Any]] = []

    strategy = venue.get("strategy", "generic")
    if strategy == "morgan_cards":
        return scrape_morgan_cards(venue, listing)
    if strategy == "met_cards":
        return scrape_met_cards(venue, listing)
    if strategy == "queens_listing":
        return scrape_queens_listing(venue, listing)
    if strategy == "guggenheim_bootstrap":
        return scrape_guggenheim_bootstrap(venue, listing)
    if strategy == "cooper_chunks":
        return scrape_cooper_chunks(venue, listing)
    if strategy == "harvard_cards":
        return scrape_harvard_cards(venue, listing)
    if strategy == "whitney_sections":
        return scrape_whitney_sections(venue, listing)
    if strategy == "listing_links":
        return scrape_listing_links(venue, listing)
    if strategy == "mfa_listings":
        return scrape_mfa_listings(venue, listing)
    if strategy == "ica_sections":
        return scrape_ica_sections(venue, listing)
    if strategy == "chase_young_page":
        return scrape_chase_young_page(venue, listing)
    if strategy == "squarespace_events":
        return scrape_squarespace_events(venue, listing)
    if strategy == "pucker_page":
        return scrape_pucker_page(venue, listing)
    if strategy == "naga_page":
        return scrape_naga_page(venue, listing)
    if strategy == "barnes_sections":
        return scrape_barnes_sections(venue, listing)
    if strategy == "philamuseum_sections":
        return scrape_philamuseum_sections(venue, listing)
    if strategy == "lenbach_chunks":
        return scrape_lenbach_chunks(venue, listing)
    if strategy == "pinakothek_listing":
        return scrape_pinakothek_listing(venue, listing)
    if strategy == "magic_gardens_page":
        return scrape_magic_gardens_page(venue, listing)
    if strategy == "soane_chunks":
        return scrape_soane_chunks(venue, listing)
    if strategy == "serpentine_listing":
        return scrape_serpentine_listing(venue, listing)
    if strategy == "vam_whatson":
        return scrape_vam_whatson(venue, listing)
    if strategy == "british_museum_listing":
        return scrape_british_museum_listing(venue, listing)
    if strategy == "courtauld_listing":
        return scrape_courtauld_listing(venue, listing)
    if strategy == "npg_sections":
        return scrape_npg_sections(venue, listing)
    if strategy == "mamm_listing":
        return scrape_mamm_listing(venue, listing)
    if strategy == "saatchi_listing":
        return scrape_saatchi_listing(venue, listing)
    if strategy == "villa_stuck_listing":
        return scrape_villa_stuck_listing(venue, listing)
    if strategy == "jewish_moscow_listing":
        return scrape_jewish_moscow_listing(venue, listing)
    if strategy == "pushkin_events":
        return scrape_pushkin_events(venue, listing)
    if strategy == "tretyakov_listing":
        return scrape_tretyakov_listing(venue, listing)
    if strategy == "mmoma_gallery":
        return scrape_mmoma_gallery(venue, listing)
    if strategy == "az_listing":
        return scrape_az_listing(venue, listing)

    items.extend(exhibitions_from_json_ld(venue, listing))

    if venue.get("single_page"):
        item = exhibition_from_page(venue, listing, venue["url"], fallback_title=venue["name"])
        return [item] if item else items

    candidates = candidate_links(venue, listing)
    for href, link_text in candidates[:MAX_DETAIL_PAGES]:
        if re.search(r"\bongoing\b", link_text, re.IGNORECASE):
            continue
        if link_has_past_dates(link_text):
            continue
        if has_forbidden_listing_text(venue, link_text):
            continue
        try:
            page = fetch_page(href)
            item = exhibition_from_page(venue, page, href, fallback_title=link_text, listing_context=link_text)
            if item:
                items.append(item)
        except (HTTPError, URLError, TimeoutError):
            continue

    if not items and not has_forbidden_listing_text(venue, listing.visible_text):
        fallback = exhibition_from_page(venue, listing, venue["url"], fallback_title=venue["name"])
        if fallback:
            items.append(fallback)
    return [item for item in dedupe_exhibitions(items) if item["status"] != "past"]


def scrape_event_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    listing = fetch_page(source["url"])
    strategy = source.get("strategy", "event_detail_links")
    if strategy == "whitney_events":
        return scrape_whitney_events(source, listing)
    if strategy == "jewish_museum_events":
        return scrape_jewish_museum_events(source, listing)
    if strategy == "queens_events":
        return scrape_queens_events(source, listing)
    if strategy == "morgan_events":
        return scrape_event_detail_links(source, listing, "/programs/")
    if strategy == "mcny_events":
        return scrape_event_detail_links(source, listing, "/event/")
    if strategy == "cooper_hewitt_events":
        return scrape_event_detail_links(source, listing, "/event/")
    return scrape_event_detail_links(source, listing, "/event/")


def scrape_whitney_events(source: dict[str, Any], listing: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    detail_cache: dict[str, dict[str, str]] = {}
    for link in listing.links:
        source_url = absolutize_url(listing.url, link.href)
        parsed_url = urlparse(source_url)
        if parsed_url.query:
            continue
        if not (parsed_url.path.startswith("/events/") or parsed_url.path.startswith("/visit/free-")):
            continue
        listing_text = clean_text(link.text)
        date_text = event_date_text_from_text(listing_text)
        parsed = parse_event_datetimes(date_text)
        if not parsed:
            continue
        title = event_title_before_date(listing_text) or clean_title(listing_text)
        details = event_details_for_url(source, source_url, listing_text, detail_cache)
        item = make_event(
            source,
            title=title,
            category=event_category(title, listing_text),
            start_at=parsed[0],
            end_at=parsed[1],
            timezone_name=EVENT_TIMEZONE,
            location=details.get("location") or source.get("location", source["name"]),
            price_text=details.get("price_text") or "Price not listed",
            availability_text=details.get("availability_text") or availability_text(listing_text),
            source_url=source_url,
        )
        items.append(item)
    return dedupe_events(items)


def scrape_jewish_museum_events(source: dict[str, Any], listing: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    detail_cache: dict[str, dict[str, str]] = {}
    for link in listing.links:
        source_url = absolutize_url(listing.url, link.href)
        if "/program/" not in urlparse(source_url).path:
            continue
        listing_text = clean_text(link.text)
        parsed = parse_event_datetimes(listing_text)
        if not parsed:
            continue
        title, category = jewish_event_title_category(listing_text)
        details = event_details_for_url(source, source_url, listing_text, detail_cache)
        items.append(
            make_event(
                source,
                title=title or event_title_before_date(listing_text),
                category=event_category(title, category),
                start_at=parsed[0],
                end_at=parsed[1],
                timezone_name=EVENT_TIMEZONE,
                location=details.get("location") or source.get("location", source["name"]),
                price_text=details.get("price_text") or "Price not listed",
                availability_text=details.get("availability_text") or availability_text(listing_text),
                source_url=source_url,
            )
        )
    return dedupe_events(items)


def scrape_queens_events(source: dict[str, Any], listing: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    detail_cache: dict[str, dict[str, str]] = {}
    for link in listing.links:
        source_url = absolutize_url(listing.url, link.href)
        if "/event/" not in urlparse(source_url).path:
            continue
        listing_text = clean_text(link.text)
        parsed = parse_event_datetimes(listing_text)
        if not parsed:
            continue
        details = event_details_for_url(source, source_url, listing_text, detail_cache)
        title = event_title_before_date(listing_text) or details.get("title") or clean_title(listing_text)
        items.append(
            make_event(
                source,
                title=title,
                category=event_category(title, listing_text),
                start_at=parsed[0],
                end_at=parsed[1],
                timezone_name=EVENT_TIMEZONE,
                location=details.get("location") or source.get("location", source["name"]),
                price_text=details.get("price_text") or "Price not listed",
                availability_text=details.get("availability_text") or availability_text(listing_text),
                source_url=source_url,
            )
        )
    return dedupe_events(items)


def scrape_event_detail_links(source: dict[str, Any], listing: ParsedPage, path_prefix: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    detail_cache: dict[str, dict[str, str]] = {}
    for source_url, title, listing_text in event_detail_links(listing, path_prefix)[:MAX_EVENT_DETAIL_PAGES]:
        if is_class_like_event(f"{title} {listing_text}"):
            continue
        details = event_details_for_url(source, source_url, listing_text, detail_cache)
        date_text = details.get("date_text") or event_date_text_from_text(listing_text)
        parsed = parse_event_datetimes(date_text)
        if not parsed:
            continue
        items.append(
            make_event(
                source,
                title=title,
                category=event_category(title, listing_text),
                start_at=parsed[0],
                end_at=parsed[1],
                timezone_name=EVENT_TIMEZONE,
                location=details.get("location") or source.get("location", source["name"]),
                price_text=details.get("price_text") or "Price not listed",
                availability_text=details.get("availability_text") or availability_text(f"{listing_text} {details.get('text', '')}"),
                source_url=source_url,
            )
        )
    return dedupe_events(items)


def event_detail_links(listing: ParsedPage, path_prefix: str) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    links: list[tuple[str, str, str]] = []
    for link in listing.links:
        source_url = absolutize_url(listing.url, link.href)
        parsed = urlparse(source_url)
        if not parsed.path.startswith(path_prefix):
            continue
        if parsed.query or source_url in seen:
            continue
        text = clean_text(link.text)
        low = text.lower()
        if not text or low in {"events", "event", "programs", "upcoming", "browse list"}:
            continue
        if any(phrase in low for phrase in ["view full event details", "order tickets", "get your tickets", "register", "join the waitlist"]):
            continue
        seen.add(source_url)
        links.append((source_url, clean_title(text), text))
    return links


def event_details_for_url(
    source: dict[str, Any],
    source_url: str,
    listing_text: str,
    cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    if source_url in cache:
        return cache[source_url]
    details: dict[str, str] = {}
    try:
        page = fetch_page(source_url)
    except (HTTPError, URLError, TimeoutError):
        cache[source_url] = details
        return details

    detail_text = clean_text(" ".join(page.chunks[:90]))
    title = extract_event_title(page, source.get("name", ""), listing_text)
    date_text = extract_event_date_text(source, page, listing_text)
    if title:
        details["title"] = title
    if date_text:
        details["date_text"] = date_text
    details["price_text"] = extract_event_price_text(page) or "Price not listed"
    details["availability_text"] = availability_text(f"{listing_text} {detail_text}")
    details["location"] = extract_event_location(source, page) or source.get("location", source.get("name", ""))
    details["category"] = event_category(title or listing_text, detail_text)
    details["text"] = detail_text
    cache[source_url] = details
    return details


def fetch_page(url: str) -> ParsedPage:
    clean_url = urldefrag(url)[0]
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        request = Request(clean_url, headers=headers)
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            content_type = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        if exc.code not in {403, 429}:
            raise
        time.sleep(RETRY_DELAY)
        retry_headers = {
            **headers,
            "Referer": f"{urlparse(clean_url).scheme}://{urlparse(clean_url).netloc}/",
            "Cache-Control": "no-cache",
        }
        request = Request(clean_url, headers=retry_headers)
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            content_type = response.headers.get_content_charset() or "utf-8"
    text = raw.decode(content_type, errors="replace")
    parser = PageParser(clean_url)
    parser.feed(text)
    parser.close()
    parser.page.raw_html = text
    return parser.page


def fetch_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "ru,en-US;q=0.8,en;q=0.7",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read()
        content_type = response.headers.get_content_charset() or "utf-8"
    return json.loads(raw.decode(content_type, errors="replace"))


def fetch_post_html(url: str, data: dict[str, str], referer: str) -> str:
    request = Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "ru,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": referer,
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read()
        content_type = response.headers.get_content_charset() or "utf-8"
    return raw.decode(content_type, errors="replace")


def scrape_met_cards(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'<article[^>]+exhibition-card[^>]*>.*?'
        r'<img[^>]+(?:src|srcSet)="(?P<img>[^"]+)".*?'
        r'<div[^>]+__title"[^>]*>.*?<a href="(?P<href>/exhibitions/[^"]+)"[^>]*>\s*<span>(?P<title>.*?)</span>.*?'
        r'<div[^>]+__meta"[^>]*>.*?<div>\s*<div>(?P<date>.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    items: list[dict[str, Any]] = []
    for match in pattern.finditer(page.raw_html):
        title = clean_title(strip_tags(match.group("title")))
        date_text = clean_date_text(strip_tags(match.group("date")))
        if is_bad_title(title, venue["name"]):
            continue
        status, start_iso, end_iso = classify_dates(date_text)
        if status not in {"current", "upcoming"}:
            continue
        image_url = best_src_from_srcset(html.unescape(match.group("img")), page.url)
        source_url = absolutize_url(page.url, html.unescape(match.group("href")))
        location = ""
        try:
            detail_page = fetch_page(source_url)
            location = met_gallery_location(detail_page)
        except (HTTPError, URLError, TimeoutError):
            pass
        items.append(
            make_item(
                venue,
                title=title,
                date_text=date_text,
                status=status,
                start_iso=start_iso,
                end_iso=end_iso,
                image_url=image_url,
                source_url=source_url,
                source_is_detail=True,
                location=location,
            )
        )
    return dedupe_exhibitions(items)


def scrape_morgan_cards(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'<div class="thumbnail">.*?<a href="(?P<href>/exhibitions/[^"]+)"[^>]*>'
        r'.*?<img[^>]+src="(?P<img>[^"]+)"'
        r'.*?views-field-title.*?field-content">(?P<title>.*?)</(?:strong|div)>'
        r'.*?views-field-field-display-date.*?field-content">(?P<date>.*?)</(?:em|div)>',
        re.IGNORECASE | re.DOTALL,
    )
    items: list[dict[str, Any]] = []
    for match in pattern.finditer(page.raw_html):
        title = clean_title(strip_tags(match.group("title")))
        date_text = clean_date_text(strip_tags(match.group("date")))
        if is_bad_title(title, venue["name"]):
            continue
        status, start_iso, end_iso = classify_dates(date_text)
        if status not in {"current", "upcoming"}:
            continue
        items.append(
            make_item(
                venue,
                title=title,
                date_text=date_text,
                status=status,
                start_iso=start_iso,
                end_iso=end_iso,
                image_url=absolutize_url(page.url, html.unescape(match.group("img"))),
                source_url=absolutize_url(page.url, html.unescape(match.group("href"))),
                source_is_detail=True,
            )
        )
    return dedupe_exhibitions(items)


def scrape_queens_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in re.split(r'<div class="archive-post-item\b', page.raw_html, flags=re.IGNORECASE)[1:]:
        block = '<div class="archive-post-item' + block.split("</div></div>", 1)[0]
        href = first_href_from_html(block, page.url, required_path="/exhibition/")
        if not href:
            continue
        image_url = first_image_from_html(block, page.url)
        link_text = queens_listing_title_from_block(block)
        try:
            detail_page = fetch_page(href)
            item = exhibition_from_page(
                venue,
                detail_page,
                href,
                fallback_title=link_text or venue["name"],
                listing_context=link_text,
            )
        except (HTTPError, URLError, TimeoutError):
            continue
        if not item:
            continue
        if image_url:
            item["image_url"] = image_url
        items.append(item)
    return dedupe_exhibitions(items)


def queens_listing_title_from_block(block: str) -> str:
    paragraph_match = re.search(r"<p[^>]*>(?P<title>.*?)</p>", block, re.IGNORECASE | re.DOTALL)
    if paragraph_match:
        return clean_title(strip_tags(paragraph_match.group("title")))
    label_match = re.search(r'aria-label=["\']Go to (?P<title>.*?)[\.\'"]', block, re.IGNORECASE | re.DOTALL)
    if label_match:
        return clean_title(strip_tags(label_match.group("title")))
    return ""


def scrape_guggenheim_bootstrap(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    marker = "const bootstrap = "
    start = page.raw_html.find(marker)
    if start == -1:
        return []
    start += len(marker)
    end = page.raw_html.find("; const footerNav", start)
    if end == -1:
        return []
    try:
        bootstrap = json.loads(page.raw_html[start:end])
    except json.JSONDecodeError:
        return []

    featured = (
        bootstrap.get("initial", {})
        .get("main", {})
        .get("posts", {})
        .get("featuredExhibitions", {})
    )
    items: list[dict[str, Any]] = []
    for section in ("on_view", "upcoming"):
        for record in featured.get(section, {}).get("items", []):
            title = clean_title(str(record.get("title", "")))
            slug = clean_text(str(record.get("slug", "")))
            if not title or not slug or is_bad_title(title, venue["name"]):
                continue

            date_text = guggenheim_date_text(record.get("dates", {}))
            status, start_iso, end_iso = classify_dates(date_text)
            if status not in {"current", "upcoming"}:
                continue

            image = image_from_value(record.get("featuredImage", {}).get("sourceUrl"), page.url)
            if not image:
                image = best_src_from_srcset(str(record.get("imageSrcset", "")), page.url)

            items.append(
                make_item(
                    venue,
                    title=title,
                    date_text=date_text,
                    status=status,
                    start_iso=start_iso,
                    end_iso=end_iso,
                    image_url=image,
                    source_url=absolutize_url(page.url, f"/exhibition/{slug}"),
                    source_is_detail=True,
                )
            )
    return dedupe_exhibitions(items)


def guggenheim_date_text(dates: Any) -> str:
    if not isinstance(dates, dict):
        return ""
    label = clean_date_text(str(dates.get("label", "")))
    start = guggenheim_date_part(dates.get("start"))
    end = guggenheim_date_part(dates.get("end"))
    parts = [part for part in [start, end] if part]
    date_text = clean_date_text(" - ".join(parts))
    if label and re.search(r"\bongoing\b", label, re.IGNORECASE):
        date_text = clean_date_text(f"{date_text} {label}")
    return date_text


def guggenheim_date_part(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    month = clean_text(str(value.get("month", "")))
    day = clean_text(str(value.get("day", "")))
    year = clean_text(str(value.get("year", "")))
    if month and day and year:
        return f"{month} {day}, {year}"
    return ""


def scrape_cooper_chunks(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in cooper_exhibition_blocks(page):
        heading_match = re.search(r"<h[12][^>]*>(?P<heading>.*?)</h[12]>", block, re.IGNORECASE | re.DOTALL)
        if not heading_match:
            continue
        heading = strip_tags(heading_match.group("heading"))
        match = re.match(r"^(?P<title>.+?)\s+ON\s+VIEW\s+(?P<date>through\s+.+)$", heading, re.IGNORECASE)
        if not match:
            continue
        title = clean_title(match.group("title"))
        date_text = clean_date_text(match.group("date"))
        if is_bad_title(title, venue["name"]):
            continue
        status, start_iso, end_iso = classify_dates(date_text)
        if status not in {"current", "upcoming"}:
            continue
        items.append(
            make_item(
                venue,
                title=title,
                date_text=date_text,
                status=status,
                start_iso=start_iso,
                end_iso=end_iso,
                image_url=first_image_from_html(block, page.url),
                source_url=cooper_source_url(block, page.url) or page.url,
                source_is_detail=bool(cooper_source_url(block, page.url)),
            )
        )
    return dedupe_exhibitions(items)


def cooper_exhibition_blocks(page: ParsedPage) -> list[str]:
    legacy_blocks = re.split(r'<div class="col-sm-4 col-\d+">', page.raw_html, flags=re.IGNORECASE)[1:]
    if legacy_blocks:
        return legacy_blocks
    parts = re.split(r"(<h[12][^>]*>.*?</h[12]>)", page.raw_html, flags=re.IGNORECASE | re.DOTALL)
    blocks: list[str] = []
    for index in range(1, len(parts), 2):
        heading = parts[index]
        heading_text = strip_tags(heading)
        if not re.search(r"\bON\s+VIEW\b", heading_text, re.IGNORECASE):
            continue
        body = parts[index + 1] if index + 1 < len(parts) else ""
        blocks.append(heading + body)
    return blocks


def cooper_source_url(block: str, page_url: str) -> str:
    for match in re.finditer(r'<a[^>]+href=["\'](?P<href>[^"\']+)["\']', block, re.IGNORECASE):
        href = html.unescape(match.group("href"))
        if "/channel/" in href:
            return absolutize_url(page_url, href)
    return ""


def scrape_harvard_cards(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in re.split(r"<article\b", page.raw_html, flags=re.IGNORECASE)[1:]:
        block = "<article" + block.split("</article>", 1)[0]
        title_match = re.search(
            r'class="[^"]*(?:exhibition-row__title|info-item__title)[^"]*"[^>]*>.*?<span[^>]*>(?P<title>.*?)</span>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        date_match = re.search(r"<time[^>]*>(?P<date>.*?)</time>", block, re.IGNORECASE | re.DOTALL)
        if not title_match or not date_match:
            continue
        title = clean_title(strip_tags(title_match.group("title")))
        date_text = clean_date_text(strip_tags(date_match.group("date")))
        source_url = (
            first_href_from_html(block, page.url, required_path="/exhibitions/")
            or source_url_for_title_in_html(page, title, required_path="/exhibitions/")
            or page.url
        )
        image_url = first_image_from_html(block, page.url)
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=source_url)
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_whitney_sections(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    link_map = whitney_link_map(page)
    for title, listing_date in whitney_section_entries(page):
        href = link_map.get(title.lower())
        if not href:
            continue
        listing_context = clean_date_text(" ".join(part for part in [title, listing_date] if part))
        try:
            detail_page = fetch_page(href)
            item = exhibition_from_page(
                venue,
                detail_page,
                href,
                fallback_title=title,
                listing_context=listing_context,
            )
        except (HTTPError, URLError, TimeoutError):
            continue
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def whitney_link_map(page: ParsedPage) -> dict[str, str]:
    links: dict[str, str] = {}
    for link in page.links:
        href = absolutize_url(page.url, link.href)
        href, _fragment = urldefrag(href)
        if "/exhibitions/" not in href:
            continue
        title, _date_text = split_listing_title_date(link.text)
        title = clean_title(title)
        if title and not is_bad_title(title, "Whitney"):
            links.setdefault(title.lower(), href)
    return links


def whitney_section_entries(page: ParsedPage) -> list[tuple[str, str]]:
    entries: list[dict[str, str]] = []
    in_exhibitions_area = False
    active_section = ""
    section_tabs = {
        "current current",
        "upcoming upcoming",
        "online online",
        "public art public art",
        "archive archive",
    }
    for chunk in page.chunks:
        text = clean_text(chunk)
        low = text.lower()
        if low == "exhibitions":
            in_exhibitions_area = True
            active_section = "current"
            continue
        if not in_exhibitions_area:
            continue
        if low in section_tabs:
            continue
        if low in {"current", "current current"}:
            active_section = "current"
            continue
        if low in {"upcoming", "upcoming upcoming"}:
            active_section = "upcoming"
            continue
        if low in {"online", "public art", "archive", "exhibition archive"}:
            break
        if active_section not in {"current", "upcoming"}:
            continue
        if has_date_text(text):
            if entries and not entries[-1]["date_text"]:
                entries[-1]["date_text"] = clean_date_text(text)
            continue
        title = clean_title(text)
        if not title or is_bad_title(title, "Whitney"):
            continue
        entries.append({"title": title, "date_text": ""})
    return [(entry["title"], entry["date_text"]) for entry in entries]


def scrape_listing_links(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    base_domain = urlparse(page.url).netloc
    includes = [part.lower() for part in venue.get("include_url_keywords", [])]
    excludes = [part.lower() for part in [*GLOBAL_EXCLUDE_URL_KEYWORDS, *venue.get("exclude_url_keywords", [])]]

    for link in page.links:
        href = absolutize_url(page.url, link.href)
        href, _fragment = urldefrag(href)
        href_l = href.lower()
        text = clean_text(link.text)
        if not href.startswith("http") or urlparse(href).netloc != base_domain:
            continue
        if includes and not any(include in href_l for include in includes):
            continue
        if any(exclude in href_l for exclude in excludes):
            continue
        if re.search(r"\bongoing\b", text, re.IGNORECASE):
            continue
        if re.search(r"\b(past|traveling|online)\s+exhibition\b", text, re.IGNORECASE):
            continue
        title, date_text = split_listing_title_date(text)
        if is_bad_title(title, venue["name"]):
            continue
        status, start_iso, end_iso = classify_dates(date_text)
        if status not in {"current", "upcoming"}:
            continue
        image_url = ""
        try:
            detail_page = fetch_page(href)
            image_url = preferred_image(venue, detail_page)
        except (HTTPError, URLError, TimeoutError):
            image_url = ""
        items.append(
            make_item(
                venue,
                title=title,
                date_text=date_text,
                status=status,
                start_iso=start_iso,
                end_iso=end_iso,
                image_url=image_url,
                source_url=href,
                source_is_detail=href != venue["url"],
            )
        )
    return dedupe_exhibitions(items)


def scrape_mfa_listings(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items = scrape_mfa_section_page(venue, page, "on view")
    upcoming_url = venue.get("upcoming_url")
    if upcoming_url:
        try:
            upcoming_page = fetch_page(str(upcoming_url))
        except (HTTPError, URLError, TimeoutError):
            upcoming_page = None
        if upcoming_page:
            items.extend(scrape_mfa_section_page(venue, upcoming_page, "upcoming exhibitions"))
    return dedupe_exhibitions(items)


def scrape_mfa_section_page(venue: dict[str, Any], page: ParsedPage, section_title: str) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    start = find_chunk(chunks, section_title)
    end = find_chunk_after(chunks, "visit us", start)
    if start == -1:
        return []
    if end == -1:
        end = len(chunks)
    items: list[dict[str, Any]] = []
    cursor = start + 1
    while cursor + 1 < end:
        title = clean_title(chunks[cursor])
        date_text = clean_date_text(chunks[cursor + 1])
        if is_bad_title(title, venue["name"]) or not has_date_text(date_text) or re.search(r"\bongoing\b", date_text, re.IGNORECASE):
            cursor += 1
            continue
        source_url = source_url_for_title(page, title, required_path="/exhibition/")
        if not source_url:
            cursor += 1
            continue
        image_url = image_at(useful_page_images(page), len(items))
        location = ""
        try:
            detail_page = fetch_page(source_url)
            image_url = preferred_image(venue, detail_page) or image_url
            location = mfa_gallery_location(detail_page)
        except (HTTPError, URLError, TimeoutError):
            pass
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=source_url, location=location)
        if item:
            items.append(item)
        cursor += 2
    return dedupe_exhibitions(items)


def scrape_ica_sections(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for title in ica_section_titles(page):
        href = source_url_for_title(page, title, required_path="/exhibitions/")
        if not href:
            continue
        try:
            detail_page = fetch_page(href)
            item = exhibition_from_page(
                venue,
                detail_page,
                href,
                fallback_title=title,
                listing_context=title,
            )
        except (HTTPError, URLError, TimeoutError):
            continue
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def ica_section_titles(page: ParsedPage) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    active_section = ""
    for chunk in page.chunks:
        text = clean_text(chunk)
        low = text.lower()
        if low in {"current", "current exhibitions"}:
            active_section = "current"
            continue
        if low in {"upcoming", "upcoming exhibitions"}:
            active_section = "upcoming"
            continue
        if low in {"past exhibitions", "currently on tour"}:
            break
        if active_section not in {"current", "upcoming"}:
            continue
        if has_date_text(text) or is_bad_title(text, "Institute of Contemporary Art/Boston"):
            continue
        title = clean_title(text)
        if not title or title.lower() in seen:
            continue
        titles.append(title)
        seen.add(title.lower())
    return titles


def scrape_chase_young_page(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page, reject=looks_like_chase_young_logo)
    items: list[dict[str, Any]] = []

    current_index = find_chunk(chunks, "current exhibit")
    if current_index != -1:
        item = chase_young_item(venue, page, chunks[current_index + 1 : current_index + 8], image_at(images, 0))
        if item:
            items.append(item)

    upcoming_index = find_chunk(chunks, "upcoming")
    if upcoming_index != -1:
        window = chunks[upcoming_index + 1 : upcoming_index + 6]
        date_index = first_date_index(window)
        if date_index > 0:
            title = clean_title(" ".join(window[:date_index]))
            item = make_listing_item(venue, page, title, window[date_index], image_at(images, 2) or image_at(images, 1))
            if item:
                items.append(item)
    return dedupe_exhibitions(items)


def chase_young_item(
    venue: dict[str, Any],
    page: ParsedPage,
    window: list[str],
    image_url: str,
) -> dict[str, Any] | None:
    date_index = first_date_index(window)
    if date_index <= 0:
        return None
    title_parts = [clean_title(part) for part in window[:date_index] if clean_title(part)]
    if len(title_parts) >= 3:
        title = f"{title_parts[0]} and {title_parts[1]}: {title_parts[2]}"
    else:
        title = ": ".join(title_parts)
    return make_listing_item(venue, page, title, window[date_index], image_url)


def scrape_squarespace_events(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page, reject=looks_like_galerie_dorsay_logo)
    items: list[dict[str, Any]] = []
    image_index = 0
    for index in range(0, max(0, len(chunks) - 3)):
        title = clean_title(chunks[index])
        start = chunks[index + 1]
        time_text = chunks[index + 2]
        end = chunks[index + 3]
        if not title or is_bad_title(title, venue["name"]) or has_date_text(title):
            continue
        if not has_date_text(start) or not has_time_text(time_text) or not has_date_text(end):
            continue
        item = make_listing_item(
            venue,
            page,
            title,
            f"{start} - {end}",
            image_at(images, image_index),
            source_url=source_url_for_title(page, title),
        )
        image_index += 1
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_pucker_page(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    start = find_chunk(chunks, "current exhibitions")
    if start == -1:
        start = 0
    window = chunks[start + 1 : start + 12]
    title = ""
    date_text = ""
    for index, chunk in enumerate(window):
        if has_date_text(chunk):
            date_text = chunk
            break
        if not title and not is_bad_title(chunk, venue["name"]):
            title = clean_title(chunk)
    item = make_listing_item(venue, page, title, date_text, image_at(images, 0))
    return [item] if item else []


def scrape_naga_page(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page, reject=looks_like_naga_logo)
    items: list[dict[str, Any]] = []
    image_index = 0

    current_start = find_chunk(chunks, "current exhibitions")
    upcoming_start = find_chunk(chunks, "upcoming")
    past_start = find_chunk(chunks, "past exhibitions")

    current_end = upcoming_start if upcoming_start != -1 else past_start if past_start != -1 else len(chunks)
    if current_start != -1:
        cursor = current_start + 1
        while cursor + 1 < current_end:
            artist = clean_title(chunks[cursor])
            title, date_text = split_listing_title_date(chunks[cursor + 1])
            if date_text and artist and title:
                item = make_listing_item(
                    venue,
                    page,
                    f"{artist}: {title}",
                    date_text,
                    image_at(images, image_index),
                )
                image_index += 1
                if item:
                    items.append(item)
                cursor += 2
            else:
                cursor += 1

    upcoming_end = past_start if past_start != -1 else len(chunks)
    if upcoming_start != -1:
        cursor = upcoming_start + 1
        while cursor + 2 < upcoming_end:
            first = clean_title(chunks[cursor])
            second = clean_title(chunks[cursor + 1])
            date_text = clean_date_text(chunks[cursor + 2])
            if not has_date_text(date_text):
                cursor += 1
                continue
            second_low = second.lower()
            if second_low.startswith("a group exhibition") or "curated by" in second_low or len(second) > 70:
                title = first
            else:
                title = f"{first}: {second}" if first and second else first or second
            item = make_listing_item(venue, page, title, date_text, image_at(images, image_index))
            image_index += 1
            if item:
                items.append(item)
            cursor += 3
    return dedupe_exhibitions(items)


def scrape_barnes_sections(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    items: list[dict[str, Any]] = []
    ranges = [
        (find_chunk(chunks, "this week"), find_chunk(chunks, "upcoming")),
        (find_chunk(chunks, "upcoming"), find_chunk(chunks, "past exhibitions")),
    ]
    for start, end in ranges:
        if start == -1:
            continue
        if end == -1 or end <= start:
            end = len(chunks)
        cursor = start + 1
        while cursor < end:
            title = clean_listing_title_label(chunks[cursor])
            if title.lower() == "the barnes collection" or is_bad_title(title, venue["name"]):
                cursor += 1
                continue
            source_url = source_url_for_title(page, title, required_path="/exhibitions/")
            if not source_url:
                cursor += 1
                continue
            try:
                detail_page = fetch_page(source_url)
                date_text = extract_date_text(detail_page, listing_context=title)
                item = make_listing_item(
                    venue,
                    detail_page,
                    title,
                    date_text,
                    preferred_image(venue, detail_page),
                    source_url=source_url,
                )
            except (HTTPError, URLError, TimeoutError):
                item = None
            if item:
                items.append(item)
            cursor += 2
    return dedupe_exhibitions(items)


def scrape_philamuseum_sections(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    current_start = find_chunk(chunks, "current exhibitions")
    ongoing_start = find_chunk_after(chunks, "ongoing exhibitions", current_start)
    upcoming_start = find_chunk_after(chunks, "upcoming exhibitions", current_start)
    archive_start = find_chunk_after(chunks, "exhibition archive", current_start)
    sections = [
        (current_start, min_after(current_start, ongoing_start, upcoming_start, archive_start)),
        (upcoming_start, min_after(upcoming_start, archive_start)),
    ]
    for start, end in sections:
        if start == -1:
            continue
        if end == -1 or end <= start:
            end = len(chunks)
        cursor = start + 1
        while cursor + 1 < end:
            title = clean_title(chunks[cursor])
            date_text = clean_date_text(chunks[cursor + 1])
            if not title or is_bad_title(title, venue["name"]) or not has_date_text(date_text):
                cursor += 1
                continue
            if re.search(r"\bongoing\b", date_text, re.IGNORECASE):
                cursor += 2
                continue
            key = title.lower()
            if key in seen_titles:
                cursor += 2
                continue
            seen_titles.add(key)
            source_url = source_url_for_title(page, title, required_path="/exhibitions/")
            item = None
            if source_url:
                try:
                    detail_page = fetch_page(source_url)
                    item = exhibition_from_page(
                        venue,
                        detail_page,
                        source_url,
                        fallback_title=title,
                        listing_context=f"{title} {date_text}",
                    )
                except (HTTPError, URLError, TimeoutError):
                    item = None
                if item:
                    items.append(item)
                cursor += 2
                continue
            if not item:
                item = make_listing_item(venue, page, title, date_text, "", source_url=source_url)
            if item:
                items.append(item)
            cursor += 2
    return dedupe_exhibitions(items)


def scrape_lenbach_chunks(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    image_index = 0

    sections = [
        (find_chunk(chunks, "on view"), find_chunk(chunks, "upcoming")),
        (find_chunk(chunks, "upcoming"), find_chunk(chunks, "past")),
    ]
    for start, end in sections:
        if start == -1:
            continue
        if end == -1 or end <= start:
            end = len(chunks)
        cursor = start + 1
        while cursor < end:
            title = clean_title(chunks[cursor])
            if is_bad_title(title, venue["name"]):
                cursor += 1
                continue
            date_index = next(
                (index for index in range(cursor + 1, min(cursor + 4, end)) if has_date_text(chunks[index])),
                -1,
            )
            if date_index == -1:
                image_index += 1
                cursor += 1
                continue
            title = re.sub(r"\s+Participate in Events$", "", title, flags=re.IGNORECASE)
            start_text = chunks[date_index]
            end_text = chunks[date_index + 1] if date_index + 1 < end and has_date_text(chunks[date_index + 1]) else ""
            date_text = clean_date_text(" - ".join(part for part in [start_text, end_text] if part))
            source_url = source_url_for_title(page, title, required_path="/details/")
            image_url = image_at(images, image_index * 2)
            if source_url:
                try:
                    detail_page = fetch_page(source_url)
                    image_url = preferred_image(venue, detail_page) or image_url
                except (HTTPError, URLError, TimeoutError):
                    pass
            item = make_listing_item(
                venue,
                page,
                title,
                date_text,
                image_url,
                source_url=source_url,
            )
            image_index += 1
            if item:
                items.append(item)
            cursor = date_index + 2
            if cursor + 1 < end and clean_text(chunks[cursor]) == clean_text(start_text) and clean_text(chunks[cursor + 1]) == clean_text(end_text):
                cursor += 2
    return dedupe_exhibitions(items)


def scrape_pinakothek_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for list_type in ("default", "preview"):
        for record in pinakothek_records(list_type):
            if not isinstance(record, dict):
                continue
            if clean_text(str(record.get("accent", ""))).lower() != "exhibition":
                continue
            title = clean_pinakothek_title(str(record.get("title", "")), str(record.get("subtitle", "")))
            preview_text = strip_tags(str(record.get("previewText", "")))
            date_text, location = pinakothek_date_and_location(preview_text)
            link = record.get("link", {}) if isinstance(record.get("link"), dict) else {}
            source_url = absolutize_url(page.url, str(link.get("url", ""))) if link.get("url") else page.url
            if location_is_room_like(location):
                try:
                    detail_page = fetch_page(source_url)
                    location = pinakothek_detail_location(detail_page) or location
                except (HTTPError, URLError, TimeoutError):
                    pass
            image = record.get("image", {}) if isinstance(record.get("image"), dict) else {}
            image_url = image_from_value(image.get("url") or image.get("desktop") or image.get("src_url"), page.url)
            item = make_listing_item(
                venue,
                page,
                title,
                date_text,
                image_url,
                source_url=source_url,
                location=location,
            )
            if item:
                items.append(item)
    return dedupe_exhibitions(items)


def pinakothek_records(list_type: str) -> list[dict[str, Any]]:
    query = urlencode({"type": "exhibition", "listType": list_type, "page": 1, "perPage": 20})
    request = Request(
        f"https://www.pinakothek.de/en/pager_api?{query}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,*/*",
            "Authorization": "Basic cGluYWtvdGhlazpjbVMyMDIwIQ==",
            "Referer": "https://www.pinakothek.de/en/exhibitions",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read()
        content_type = response.headers.get_content_charset() or "utf-8"
    data = json.loads(raw.decode(content_type, errors="replace"))
    return data if isinstance(data, list) else []


def clean_pinakothek_title(title: str, subtitle: str) -> str:
    title = humanize_all_caps_phrases(clean_text(title))
    subtitle = humanize_all_caps_phrases(clean_text(subtitle))
    return clean_title(" ".join(part for part in [title, subtitle] if part))


def humanize_all_caps_phrases(value: str) -> str:
    words = value.split()
    styled: list[str] = []
    run: list[str] = []

    def flush_run() -> None:
        if not run:
            return
        styled.append(humanize_all_caps_title(" ".join(run)) if len(run) >= 2 else " ".join(run))
        run.clear()

    for word in words:
        letters = re.sub(r"[^A-Za-z]", "", word)
        if not letters and run and re.match(r"^[&+/:-]+$", word):
            run.append(word)
            continue
        if letters and not any(char.islower() for char in letters):
            run.append(word)
            continue
        flush_run()
        styled.append(word)
    flush_run()
    return clean_text(" ".join(styled))


def pinakothek_date_and_location(value: str) -> tuple[str, str]:
    text = clean_text(value)
    match = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}\s*[-–—]\s*\d{1,2}\.\d{1,2}\.\d{4}", text)
    if not match:
        return "", ""
    date_text = clean_date_text(match.group(0))
    before = pinakothek_location_label(text[: match.start()])
    after = text[match.end() :]
    paren_match = re.search(r"\((?P<location>[^)]+)\)", after)
    location = pinakothek_location_label(paren_match.group("location")) if paren_match else before
    return date_text, location


def pinakothek_location_label(value: str) -> str:
    text = clean_text(value)
    low = text.lower()
    labels = [
        "Pinakothek der Moderne",
        "Alte Pinakothek",
        "Neue Pinakothek",
        "Sammlung Schack",
        "Museum Brandhorst",
    ]
    for label in labels:
        if label.lower() in low:
            return label
    return clean_location_text(text)


def location_is_room_like(value: str) -> bool:
    low = clean_text(value).lower()
    return not low or any(word in low for word in ["room", "floor", "east", "west", "gallery"])


def pinakothek_detail_location(page: ParsedPage) -> str:
    chunks = page_chunks(page)
    body = clean_text(" ".join(chunks[5:30]))
    low = body.lower()
    if "herrenchiemsee" in low:
        return "Herrenchiemsee Palace"
    if re.search(r"\bat (?:the )?alte pinakothek\b", low) or "alte pinakothek münchen" in low:
        return "Alte Pinakothek"
    if re.search(r"\bat (?:the )?pinakothek der moderne\b", low) or "pinakothek der moderne presents" in low:
        return "Pinakothek der Moderne"
    for label in ["Museum Brandhorst", "Sammlung Schack", "Neue Pinakothek", "Alte Pinakothek", "Pinakothek der Moderne"]:
        if label.lower() in low:
            return label
    return ""


def scrape_magic_gardens_page(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page, reject=looks_like_magic_gardens_logo)
    starts = [index for index, chunk in enumerate(chunks) if clean_text(chunk).lower() == "current exhibitions"]
    start = starts[-1] if starts else 0
    for index in range(start + 1, min(len(chunks) - 1, start + 12)):
        title = clean_title(chunks[index])
        date_text = clean_date_text(chunks[index + 1])
        if is_bad_title(title, venue["name"]) or not has_date_text(date_text):
            continue
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, 0),
            source_url=venue["url"],
        )
        return [item] if item else []
    return []


def scrape_soane_chunks(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    start = find_chunk(chunks, "archive")
    if start == -1:
        start = 19
    cursor = start + 1
    image_index = 0
    while cursor + 2 < len(chunks):
        title = clean_title(chunks[cursor])
        if title.lower() == "find us":
            break
        if is_bad_title(title, venue["name"]) or not has_date_text(chunks[cursor + 1]) or not has_date_text(chunks[cursor + 2]):
            cursor += 1
            continue
        context = " ".join(chunks[cursor : min(cursor + 5, len(chunks))])
        if has_forbidden_listing_text(venue, context):
            cursor += 3
            image_index += 1
            continue
        date_text = f"{chunks[cursor + 1]} - {chunks[cursor + 2]}"
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, image_index),
            source_url=source_url_for_title(page, title, required_path="/whats-on/"),
        )
        image_index += 1
        if item:
            items.append(item)
        cursor += 3
    return dedupe_exhibitions(items)


def scrape_serpentine_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    items: list[dict[str, Any]] = []
    start = find_chunk(chunks, "exhibitions")
    end = find_chunk_after(chunks, "events", start)
    if start == -1:
        return items
    if end == -1:
        end = len(chunks)
    cursor = start + 1
    while cursor < end:
        title = clean_title(chunks[cursor])
        if is_bad_title(title, venue["name"]):
            cursor += 1
            continue
        source_url = source_url_for_title(page, title, required_path="/whats-on/")
        item = None
        if source_url:
            try:
                detail_page = fetch_page(source_url)
                structured_items = exhibitions_from_json_ld(venue, detail_page)
                item = structured_items[0] if structured_items else None
                if item:
                    item["source_url"] = source_url
                    item["source_is_detail"] = True
                else:
                    item = exhibition_from_page(venue, detail_page, source_url, fallback_title=title, listing_context=title)
            except (HTTPError, URLError, TimeoutError):
                item = None
        if item:
            items.append(item)
        cursor += 2
    return dedupe_exhibitions(items)


def scrape_vam_whatson(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    start = find_chunk_after(chunks, "exhibitions", 10)
    end = find_chunk_after(chunks, "featured events", start)
    if start == -1:
        return items
    if end == -1:
        end = len(chunks)
    image_index = 0
    cursor = start + 1
    while cursor + 3 < end:
        if clean_text(chunks[cursor]).lower() != "exhibition":
            cursor += 1
            continue
        title = clean_listing_title_label(chunks[cursor + 1])
        date_text = chunks[cursor + 2]
        location = clean_location_text(chunks[cursor + 3])
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, image_index),
            source_url=source_url_for_title(page, title, required_path="/whatson/"),
            location=location,
        )
        image_index += 1
        if item:
            items.append(item)
        cursor += 4
    return dedupe_exhibitions(items)


def scrape_british_museum_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    start = find_chunk(chunks, "special exhibitions")
    end = find_chunk(chunks, "highlight events")
    if start == -1:
        return items
    if end == -1:
        end = len(chunks)
    image_index = 0
    for index in range(start + 1, max(start + 1, end - 2)):
        if clean_text(chunks[index + 1]).lower() != "exhibition":
            continue
        title = clean_listing_title_label(chunks[index])
        date_text = chunks[index + 2]
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, image_index),
            source_url=source_url_for_title(page, title, required_path="/exhibitions-events/"),
        )
        image_index += 1
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_courtauld_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    for index in range(0, max(0, len(chunks) - 2)):
        metadata = chunks[index]
        if "exhibition" not in metadata.lower() or "collection" in metadata.lower():
            continue
        title = clean_listing_title_label(chunks[index + 1])
        date_text = chunks[index + 2]
        location = "Vernon Square" if "vernon" in metadata.lower() else "Somerset House"
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, len(items)),
            source_url=source_url_for_title(page, title, required_path="/whats-on/"),
            location=location,
        )
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_npg_sections(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    start = find_chunk_after(chunks, "exhibitions", 30)
    end = find_chunk_after(chunks, "club npg", start)
    if start == -1:
        return items
    if end == -1:
        end = len(chunks)
    cursor = start + 1
    image_index = 0
    while cursor + 1 < end:
        title = clean_listing_title_label(chunks[cursor])
        date_text = chunks[cursor + 1]
        if not has_date_text(date_text):
            cursor += 1
            continue
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, image_index),
            source_url=source_url_for_title(page, title, required_path="/whatson/whatson/exhibitions/"),
        )
        image_index += 1
        if item:
            items.append(item)
        cursor += 2
    return dedupe_exhibitions(items)


def scrape_mamm_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    items: list[dict[str, Any]] = []
    start = find_chunk(chunks, "выставки")
    end = find_chunk_after(chunks, "выставки на других площадках", start)
    if start == -1:
        return items
    if end == -1:
        end = len(chunks)
    for title in chunks[start + 1 : end]:
        title = clean_listing_title_label(title)
        if is_bad_title(title, venue["name"]):
            continue
        source_url = source_url_for_title(page, title, required_path="/exhibitions/")
        if not source_url or source_url.rstrip("/").endswith("/exhibitions"):
            continue
        try:
            detail_page = fetch_page(source_url)
            item = exhibition_from_page(venue, detail_page, source_url, fallback_title=title, listing_context=title)
        except (HTTPError, URLError, TimeoutError):
            item = None
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_saatchi_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    images = useful_page_images(page)
    items: list[dict[str, Any]] = []
    for index in range(0, max(0, len(chunks) - 1)):
        title = clean_listing_title_label(chunks[index])
        date_text = chunks[index + 1]
        if is_bad_title(title, venue["name"]) or not has_date_text(date_text):
            continue
        if not re.search(rf"\b\d{{1,2}}\s+(?:{MONTH_RE})\s*[-–—]\s*\d{{1,2}}\s+(?:{MONTH_RE})", date_text, re.IGNORECASE):
            continue
        item = make_listing_item(
            venue,
            page,
            title,
            date_text,
            image_at(images, len(items)),
            source_url=source_url_for_title(page, title, required_path="/whats-on/") or page.url,
        )
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_villa_stuck_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    chunks = page_chunks(page)
    links = [
        link
        for link in page.links
        if "/programm/detail/" in absolutize_url(page.url, link.href).lower()
        and clean_title(link.text)
        and not is_bad_title(clean_title(link.text), venue["name"])
    ]
    items: list[dict[str, Any]] = []
    current_start = find_chunk(chunks, "aktuelle ausstellungen")
    preview_start = find_chunk_after(chunks, "ausstellungsvorschau", current_start)
    if current_start == -1:
        return items
    end = preview_start if preview_start != -1 else len(chunks)
    dates: list[str] = []
    cursor = current_start + 1
    while cursor + 1 < end:
        if has_date_text(chunks[cursor]) and has_date_text(chunks[cursor + 1]):
            dates.append(f"{chunks[cursor]} - {chunks[cursor + 1]}")
            cursor += 3
        else:
            cursor += 1
    for index, date_text in enumerate(dates):
        if index >= len(links):
            break
        link = links[index]
        title = clean_listing_title_label(link.text)
        source_url = absolutize_url(page.url, link.href)
        try:
            detail_page = fetch_page(source_url)
            image_url = preferred_image(venue, detail_page)
        except (HTTPError, URLError, TimeoutError):
            image_url = ""
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=source_url)
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_jewish_moscow_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    images = useful_page_images(page)
    links: list[Link] = []
    for link in page.links:
        href = absolutize_url(page.url, link.href)
        text = clean_title(link.text)
        if "/exhibitions/" not in href or href.rstrip("/").endswith("/exhibitions"):
            continue
        if text.startswith("Обзорная экскурсия") or "/excursions/" in href:
            break
        if "выставочные программы" in text.lower():
            continue
        if text and not is_bad_title(text, venue["name"]):
            links.append(Link(href, text))
    for index, link in enumerate(links[:4]):
        try:
            detail_page = fetch_page(link.href)
            item = exhibition_from_page(
                venue,
                detail_page,
                link.href,
                fallback_title=link.text,
                listing_context=link.text,
            )
        except (HTTPError, URLError, TimeoutError):
            item = None
        if item:
            if index < len(images):
                item["image_url"] = images[index]
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_pushkin_events(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    today = date.today()
    html_text = fetch_post_html(
        "https://pushkinmuseum.art/events/blocks/events_list.php",
        {
            "filter": "today",
            "day0": str(today.day),
            "month0": str(today.month - 1),
            "year0": str(today.year),
            "day1": str(today.day),
            "month1": str(today.month),
            "year1": str(today.year),
            "building": "0",
            "categories": "369",
            "show_categories_list": "0",
            "keywords": "",
            "lang": "ru",
            "layout": "masonry",
        },
        "https://pushkinmuseum.art/events?lang=ru",
    )
    items: list[dict[str, Any]] = []
    for block in re.split(r'<div class="item item--card\b', html_text, flags=re.IGNORECASE)[1:]:
        block = '<div class="item item--card' + block.split('<div class="item item--card', 1)[0]
        if "desc__type" in block and "Выставка" not in strip_tags(block):
            continue
        title_match = re.search(r'<div class="font-gmtext">\s*<p>(?P<title>.*?)</p>', block, re.IGNORECASE | re.DOTALL)
        date_match = re.search(r'<div class="desc__date">(?P<date>.*?)</div>', block, re.IGNORECASE | re.DOTALL)
        place_match = re.search(r'<a class="desc__place"[^>]*>\s*<span>(?P<place>.*?)</span>', block, re.IGNORECASE | re.DOTALL)
        href = first_href_from_html(block, page.url, required_path="/events/")
        image_url = first_image_from_html(block, page.url)
        if not title_match or not date_match or not href:
            continue
        title = clean_title(strip_tags(title_match.group("title")))
        date_text = clean_date_text(strip_tags(date_match.group("date")))
        location = pushkin_location_label(strip_tags(place_match.group("place")) if place_match else "")
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=href, location=location)
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_tretyakov_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    data = fetch_json("https://www.tretyakovgallery.ru/api/content/exhibitions/?page_size=50&page=1&main=Y&archive=n")
    records = data.get("data", {}).get("items", []) if isinstance(data, dict) else []
    items: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("archive"):
            continue
        title = clean_title(str(record.get("name", "")))
        date_text = clean_date_text(" - ".join(part for part in [str(record.get("startDate", "")), str(record.get("endDate", ""))] if part))
        source_url = absolutize_url("https://www.tretyakovgallery.ru/", str(record.get("url", "")))
        image_url = absolutize_url("https://www.tretyakovgallery.ru/", str(record.get("picture", "")))
        place = record.get("place", {}) if isinstance(record.get("place"), dict) else {}
        location = tretyakov_location_label(str(place.get("name", "")))
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=source_url, location=location)
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_mmoma_gallery(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    records = fetch_json("https://mmoma.ru/api/page/19/children")
    if not isinstance(records, list):
        return []
    items: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        tags = " ".join(str(tag.get("title", "")) for tag in record.get("tags", []) if isinstance(tag, dict)).lower()
        if "онлайн" in tags or "online" in tags:
            continue
        title = clean_title(str(record.get("title", "")))
        if is_bad_title(title, venue["name"]):
            continue
        date_text = clean_date_text(" - ".join(part for part in [str(record.get("periodStart", "")), str(record.get("periodEnd", ""))] if part))
        source_url = absolutize_url("https://mmoma.ru/", str(record.get("path", "")))
        image_url = mmoma_image_url(str(record.get("image", "")))
        try:
            detail_page = fetch_page(source_url)
            image_url = image_at(useful_page_images(detail_page), 0) or image_url
        except (HTTPError, URLError, TimeoutError):
            pass
        location = mmoma_location_from_record(record)
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=source_url, location=location)
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def scrape_az_listing(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r'(?P<block><div class="scheduleItem"(?=[\s>]).*?)(?=<div class="scheduleItem"(?=[\s>])|<div class="show-more"|</main>)',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(page.raw_html):
        block = match.group("block")
        if "Выставка" not in strip_tags(block):
            continue
        title_match = re.search(r'<div class="scheduleItem__title">\s*<h3>(?P<title>.*?)</h3>', block, re.IGNORECASE | re.DOTALL)
        date_match = re.search(r'<div class="scheduleItem__time">(?P<date>.*?)</div>', block, re.IGNORECASE | re.DOTALL)
        href = first_href_from_html(block, page.url, required_path="/event/")
        image_url = first_image_from_html(block, page.url)
        if not title_match or not date_match or not href:
            continue
        title = clean_title(strip_tags(title_match.group("title")))
        date_text = clean_date_text(strip_tags(date_match.group("date")))
        item = make_listing_item(venue, page, title, date_text, image_url, source_url=href)
        if item:
            items.append(item)
    return dedupe_exhibitions(items)


def pushkin_location_label(value: str) -> str:
    low = clean_text(value).lower()
    if "галере" in low:
        return "галерея"
    if "глав" in low:
        return "главное здание"
    return clean_location_text(value)


def tretyakov_location_label(value: str) -> str:
    low = clean_text(value).lower()
    if "кадаш" in low:
        return "корпус на кадашёвке"
    if "новая" in low:
        return "новая третьяковка"
    if "инженер" in low:
        return "инженерный корпус"
    if "третьяков" in low:
        return "третьяковская галерея"
    return clean_location_text(value)


def mmoma_location_from_record(record: dict[str, Any]) -> str:
    path = str(record.get("path", "")).lower()
    title = " ".join([str(record.get("title", "")), path]).lower()
    checks = [
        ("sidur", "музей сидура"),
        ("nalband", "музей налбандяна"),
        ("petrov", "петровка 25"),
        ("gogol", "гоголевский 10"),
        ("ermola", "ермолаевский 17"),
    ]
    for needle, label in checks:
        if needle in title:
            return label
    detail_path = str(record.get("path", ""))
    if detail_path:
        try:
            content = fetch_json(f"https://mmoma.ru/api/page/{record.get('id')}/content")
            location = mmoma_location_from_content(content)
            if location:
                return location
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, TypeError):
            pass
    return ""


def mmoma_location_from_content(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    text = json.dumps(content, ensure_ascii=False).lower()
    if "сидур" in text:
        return "музей сидура"
    if "налбанд" in text:
        return "музей налбандяна"
    if "петровка" in text or "petrovka" in text:
        return "петровка 25"
    if "гоголев" in text or "gogolev" in text:
        return "гоголевский 10"
    if "ермолаев" in text or "ermolayev" in text:
        return "ермолаевский 17"
    return ""


def mmoma_image_url(link: str) -> str:
    if not link:
        return ""
    query = urlencode({"link": link, "size": "medium"})
    return f"https://admin.mmoma.ru/api/files/preview/link?{query}"


def clean_listing_title_label(value: str) -> str:
    value = clean_title(value)
    value = re.sub(r"\s+\.\s+(?:Book now|Free|Coming soon|Member booking open|Final weeks|Reopens?)\b.*$", "", value, flags=re.IGNORECASE)
    return clean_title(value)


def min_after(start: int, *values: int) -> int:
    positives = [value for value in values if value != -1 and value > start]
    return min(positives) if positives else -1


def make_listing_item(
    venue: dict[str, Any],
    page: ParsedPage,
    title: str,
    date_text: str,
    image_url: str,
    source_url: str = "",
    location: str = "",
) -> dict[str, Any] | None:
    title = clean_title(title)
    date_text = clean_date_text(date_text)
    if not title or is_bad_title(title, venue["name"]) or not has_date_text(date_text):
        return None
    if has_forbidden_listing_text(venue, f"{title} {date_text}"):
        return None
    status, start_iso, end_iso = classify_dates(date_text)
    if status not in {"current", "upcoming"}:
        return None
    source_url = source_url or venue["url"]
    item = make_item(
        venue,
        title=title,
        date_text=date_text,
        status=status,
        start_iso=start_iso,
        end_iso=end_iso,
        image_url=image_url,
        source_url=source_url,
        source_is_detail=source_url != venue["url"],
        location=location,
    )
    if not has_displayable_date(item):
        return None
    if not is_relevant_location(venue, item, page.visible_text):
        return None
    return item


def page_chunks(page: ParsedPage) -> list[str]:
    return [clean_text(chunk) for chunk in page.chunks if clean_text(chunk)]


def find_chunk(chunks: list[str], needle: str) -> int:
    needle = needle.lower()
    for index, chunk in enumerate(chunks):
        low = chunk.lower()
        if low == needle or low.startswith(f"{needle} "):
            return index
    return -1


def find_chunk_after(chunks: list[str], needle: str, start: int) -> int:
    needle = needle.lower()
    for index, chunk in enumerate(chunks):
        if index <= start:
            continue
        low = chunk.lower()
        if low == needle or low.startswith(f"{needle} "):
            return index
    return -1


def first_date_index(chunks: list[str]) -> int:
    for index, chunk in enumerate(chunks):
        if has_date_text(chunk):
            return index
    return -1


def has_time_text(text: str) -> bool:
    return bool(re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", text, re.IGNORECASE))


def useful_page_images(page: ParsedPage, reject: Any = None) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    for src in page.images:
        image = absolutize_url(page.url, src)
        if "static.wixstatic.com/media/" in image:
            image = normalize_wix_image(image)
        if not is_useful_image(image):
            continue
        if reject and reject(image):
            continue
        if image in seen:
            continue
        images.append(image)
        seen.add(image)
    return images


def image_at(images: list[str], index: int) -> str:
    if 0 <= index < len(images):
        return images[index]
    return images[0] if images else ""


def source_url_for_title(page: ParsedPage, title: str, required_path: str = "") -> str:
    title_key = comparable_text(title)
    title_words = [word for word in title_key.split() if len(word) > 2]
    if not title_words:
        return ""
    for link in page.links:
        href = absolutize_url(page.url, link.href)
        href, _fragment = urldefrag(href)
        href_l = href.lower()
        if required_path and required_path not in href_l:
            continue
        if "format=ical" in href_l or href_l.endswith(".ics"):
            continue
        haystack = comparable_text(f"{link.text} {urlparse(href).path}")
        if title_key and title_key in haystack:
            return href
        words_to_match = title_words[: min(4, len(title_words))]
        if len(words_to_match) >= 2 and all(word in haystack for word in words_to_match):
            return href
    return ""


def source_url_for_title_in_html(page: ParsedPage, title: str, required_path: str = "") -> str:
    if not title:
        return ""
    positions = [page.raw_html.find(title), page.raw_html.find(html.escape(title))]
    positions = [position for position in positions if position != -1]
    if not positions:
        return ""
    position = min(positions)
    snippet = page.raw_html[max(0, position - 1800) : position + 300]
    matches = list(re.finditer(r'<a\b[^>]+href=["\'](?P<href>[^"\']+)["\']', snippet, re.IGNORECASE))
    for match in reversed(matches):
        href = absolutize_url(page.url, match.group("href"))
        href, _fragment = urldefrag(href)
        if required_path and required_path not in href.lower():
            continue
        return href
    return ""


def comparable_text(text: str) -> str:
    text = html.unescape(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def looks_like_chase_young_logo(url: str) -> bool:
    lower = url.lower()
    return "logo" in lower or "unknown-1" in lower or "chase" in lower and "young" in lower and "media" not in lower


def looks_like_galerie_dorsay_logo(url: str) -> bool:
    lower = url.lower()
    return "logo" in lower or "gdo" in lower and "black" in lower


def looks_like_naga_logo(url: str) -> bool:
    lower = url.lower()
    return "logo" in lower or "gallery-naga" in lower and "logo" in lower


def looks_like_magic_gardens_logo(url: str) -> bool:
    lower = url.lower()
    return "logo" in lower or "quantserve" in lower or lower.endswith(".gif")


def exhibitions_from_json_ld(venue: dict[str, Any], page: ParsedPage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for script in page.json_ld:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        nodes = flatten_json_ld(data)
        for node in nodes:
            node_type = node.get("@type", "")
            if isinstance(node_type, list):
                type_text = " ".join(str(part) for part in node_type)
            else:
                type_text = str(node_type)
            if not re.search(r"Event|Exhibition", type_text, re.IGNORECASE):
                continue
            title = clean_title(str(node.get("name", "")))
            if not title or is_bad_title(title, venue["name"]):
                continue
            if has_forbidden_listing_text(venue, f"{title} {page.visible_text}"):
                continue
            source_url = absolutize_url(page.url, str(node.get("url") or page.url))
            image = image_from_value(node.get("image"), page.url) or preferred_image(venue, page)
            start = str(node.get("startDate", ""))
            end = str(node.get("endDate", ""))
            date_text = clean_date_text(" - ".join(part for part in [start, end] if part))
            if not date_text:
                date_text = extract_date_text(page)
            status, start_iso, end_iso = classify_dates(date_text)
            item = make_item(
                venue,
                title=title,
                date_text=date_text,
                status=status,
                start_iso=start_iso,
                end_iso=end_iso,
                image_url=image,
                source_url=source_url,
                source_is_detail=source_url != venue["url"],
            )
            if is_relevant_location(venue, item, page.visible_text):
                items.append(item)
    return items


def flatten_json_ld(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [node for item in data for node in flatten_json_ld(item)]
    if not isinstance(data, dict):
        return []
    nodes: list[dict[str, Any]] = []
    if "@graph" in data:
        nodes.extend(flatten_json_ld(data["@graph"]))
    nodes.append(data)
    return nodes


def candidate_links(venue: dict[str, Any], page: ParsedPage) -> list[tuple[str, str]]:
    seen: set[str] = set()
    candidates: list[tuple[int, str, str]] = []
    base_domain = urlparse(page.url).netloc
    includes = [part.lower() for part in venue.get("include_url_keywords", [])]
    excludes = [part.lower() for part in [*GLOBAL_EXCLUDE_URL_KEYWORDS, *venue.get("exclude_url_keywords", [])]]

    for link in page.links:
        href = absolutize_url(page.url, link.href)
        href, _fragment = urldefrag(href)
        parsed = urlparse(href)
        href_l = href.lower()
        text = clean_title(link.text)
        if not href.startswith("http") or parsed.netloc != base_domain:
            continue
        if href in seen or href == urldefrag(venue["url"])[0]:
            continue
        if any(exclude in href_l for exclude in excludes):
            continue
        if includes and not any(include in href_l for include in includes):
            continue
        if is_bad_title(text, venue["name"]):
            continue
        if has_forbidden_listing_text(venue, text):
            continue

        score = 0
        if any(word in href_l for word in ["exhibition", "exhibitions", "current"]):
            score += 4
        if has_date_text(text):
            score += 3
            link_status = classify_dates(text)[0]
            if link_status == "past":
                score -= 20
            elif link_status in {"current", "upcoming"}:
                score += 12
        if re.search(r"\b(on view|current|upcoming|opening|through)\b", text, re.IGNORECASE):
            score += 2
        if is_relevant_location_text(venue, text):
            score += 4
        if 4 <= len(text) <= 95:
            score += 1
        if score <= 0:
            continue
        candidates.append((score, href, text))
        seen.add(href)

    candidates.sort(key=lambda item: (-item[0], item[2].lower()))
    return [(href, text) for _score, href, text in candidates]


def exhibition_from_page(
    venue: dict[str, Any],
    page: ParsedPage,
    source_url: str,
    fallback_title: str,
    listing_context: str = "",
) -> dict[str, Any] | None:
    title = extract_venue_specific_title(venue, page) or extract_title(page, venue["name"], fallback_title)
    date_text = extract_date_text(page, listing_context=listing_context)
    if venue.get("require_embedded_dates") and not embedded_date_range_text(page.raw_html):
        return None
    if has_forbidden_listing_text(venue, f"{title} {date_text} {page.visible_text}"):
        return None
    if venue.get("name") == "MoMA" and not moma_is_exhibition_page(page):
        return None
    if not title or is_bad_title(title, venue["name"]):
        title = extract_title_from_date_context(page, venue["name"])
    if not title or is_bad_title(title, venue["name"]):
        return None
    location = extract_location_text(venue, page)

    status, start_iso, end_iso = classify_dates(date_text)
    if status == "past":
        return None

    item = make_item(
        venue,
        title=title,
        date_text=date_text,
        status=status,
        start_iso=start_iso,
        end_iso=end_iso,
        image_url=preferred_image(venue, page),
        source_url=source_url,
        source_is_detail=source_url != venue["url"],
        location=location,
    )
    if not is_relevant_location(venue, item, page.visible_text):
        return None
    return item


def extract_venue_specific_title(venue: dict[str, Any], page: ParsedPage) -> str:
    if venue.get("name") == "Van Der Plas Gallery":
        return extract_van_der_plas_title(page)
    if venue.get("name") == "МАММ":
        title = page.title
        title = re.sub(r"^Мультимедиа\s+Арт\s+Музей,\s*Москва\s*\|\s*Выставки\s*\|\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^Выставки:\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*\(Мультимедиа\s+Арт\s+Музей,\s*Москва\)\s*$", "", title, flags=re.IGNORECASE)
        return clean_title(title)
    return ""


def extract_van_der_plas_title(page: ParsedPage) -> str:
    for index, chunk in enumerate(page.chunks):
        if clean_text(chunk).lower() != "van der plas gallery presents":
            continue
        for candidate in page.chunks[index + 1 : index + 6]:
            title = clean_title(candidate)
            if title and not is_bad_title(title, "Van Der Plas Gallery"):
                return title
    return ""


def extract_location_text(venue: dict[str, Any], page: ParsedPage) -> str:
    if venue.get("name") == "MoMA":
        return moma_floor_location(page)

    label_names = {"where", "location", "venue"}
    chunks = page_chunks(page)
    for index, chunk in enumerate(chunks[:240]):
        if clean_text(chunk).lower().strip(":") not in label_names:
            continue
        for candidate in chunks[index + 1 : index + 4]:
            location = clean_location_text(candidate)
            if location:
                return location
    return ""


def moma_floor_location(page: ParsedPage) -> str:
    for chunk in page_chunks(page)[:90]:
        match = re.search(r"\b(?:MoMA|Education Center),\s*(?P<floor>Floor\s+[A-Za-z0-9]+)\b", chunk)
        if match:
            return clean_location_text(match.group("floor"))
    return ""


def moma_is_exhibition_page(page: ParsedPage) -> bool:
    for chunk in page_chunks(page)[:100]:
        normalized = clean_text(chunk).lower()
        if normalized in {"exhibition", "installation"}:
            return normalized == "exhibition"
    return False


def met_gallery_location(page: ParsedPage) -> str:
    matches = re.findall(r"Gallery\s+[A-Za-z0-9-]+", html.unescape(page.raw_html), re.IGNORECASE)
    for match in matches:
        location = clean_location_text(match)
        if location:
            return location
    return ""


def mfa_gallery_location(page: ParsedPage) -> str:
    for chunk in page_chunks(page):
        match = re.search(r"\bGallery\s+[A-Za-z]*\d[A-Za-z0-9-]*\b", chunk)
        if match:
            location = clean_location_text(match.group(0))
            if location:
                return location
    return ""


def clean_location_text(value: str) -> str:
    value = clean_text(value)
    if not value or has_date_text(value):
        return ""
    low = value.lower().strip(":")
    if low in {"tickets", "free with museum admission", "membership", "about", "when", "where", "location", "venue"}:
        return ""
    if len(value) > 100:
        return ""
    value = re.sub(r"\s*,\s*", ", ", value)
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) > 1 and len({part.lower() for part in parts}) == 1:
        value = parts[0]
    return value


def make_item(
    venue: dict[str, Any],
    *,
    title: str,
    date_text: str,
    status: str,
    start_iso: str | None,
    end_iso: str | None,
    image_url: str,
    source_url: str,
    source_is_detail: bool,
    location: str = "",
) -> dict[str, Any]:
    raw_date_text = clean_date_text(date_text)
    display_date_text = format_display_date(status, start_iso, end_iso, raw_date_text)
    identity = "|".join([venue["city"], venue["tab"], venue["name"], title, raw_date_text, source_url])
    item_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    return {
        "id": item_id,
        "city": venue["city"],
        "tab": venue["tab"],
        "venue": venue["name"],
        "venue_order": venue.get("venue_order", 999),
        "tab_order": venue.get("tab_order", 999),
        "venue_url": venue["url"],
        "title": title,
        "date_text": display_date_text,
        "raw_date_text": raw_date_text,
        "status": status if status in {"current", "upcoming", "unknown"} else "unknown",
        "start_date": start_iso,
        "end_date": end_iso,
        "location": location or venue.get("location", venue["city"]),
        "image_url": image_url,
        "source_url": source_url,
        "source_is_detail": source_is_detail,
    }


def make_event(
    source: dict[str, Any],
    *,
    title: str,
    category: str,
    start_at: str,
    end_at: str,
    timezone_name: str,
    location: str,
    price_text: str,
    availability_text: str,
    source_url: str,
) -> dict[str, Any]:
    title = clean_title(title)
    price_text = clean_text(price_text) or "Price not listed"
    identity = "|".join([source["city"], source["name"], title, start_at, source_url])
    item_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    return {
        "id": item_id,
        "city": source["city"],
        "venue": source["name"],
        "venue_order": source.get("venue_order", 999),
        "venue_url": source["url"],
        "title": title,
        "category": category or "Events",
        "start_at": start_at,
        "end_at": end_at,
        "timezone": timezone_name,
        "location": clean_location_text(location) or source.get("location", source["name"]),
        "price_text": price_text,
        "price": parse_price_value(price_text),
        "availability_text": clean_text(availability_text),
        "source_url": source_url,
    }


def is_displayable_event(item: dict[str, Any]) -> bool:
    title = item.get("title", "")
    if not title or not item.get("start_at") or not item.get("source_url"):
        return False
    combined = " ".join(
        str(item.get(key, ""))
        for key in ["title", "category", "price_text", "availability_text", "location"]
    )
    if is_class_like_event(combined) or is_member_only_event(combined):
        return False
    start = parse_local_datetime(str(item.get("start_at", "")))
    end = parse_local_datetime(str(item.get("end_at", "")))
    if not start:
        return False
    today = date.today()
    if start.date() < today:
        return False
    if start.date() > today + timedelta(days=180):
        return False
    if end and end.date() != start.date():
        return False
    return True


def is_class_like_event(value: str) -> bool:
    low = clean_text(value).lower()
    class_patterns = [
        r"\bclasses?\b",
        r"\bworkshops?\b",
        r"\bcourses?\b",
        r"\bcamps?\b",
        r"\bsummer camp\b",
        r"\bprofessional development\b",
        r"\beducator tour and workshop\b",
        r"\bteacher workshop\b",
        r"\bteen workshop\b",
        r"\bkids art studio\b",
    ]
    return any(re.search(pattern, low) for pattern in class_patterns)


def is_member_only_event(value: str) -> bool:
    low = clean_text(value).lower()
    member_only_phrases = [
        "member nights",
        "member morning",
        "member mornings",
        "members' thursdays",
        "members only",
        "member-only",
        "exclusively to members",
        "free for members",
        "for members",
    ]
    if "non-member" in low or "nonmembers" in low or "non-members" in low:
        return False
    return any(phrase in low for phrase in member_only_phrases)


def dedupe_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = "|".join(
            [
                item.get("city", ""),
                item.get("venue", ""),
                item.get("title", "").lower(),
                item.get("start_at", ""),
            ]
        )
        existing = deduped.get(key)
        if not existing:
            deduped[key] = item
            continue
        if item.get("price_text") != "Price not listed" and existing.get("price_text") == "Price not listed":
            deduped[key] = item
        elif item.get("availability_text") and not existing.get("availability_text"):
            deduped[key] = item
    return list(deduped.values())


def event_sort_key(item: dict[str, Any]) -> tuple[str, str, int, str]:
    return (
        item.get("city", ""),
        item.get("start_at", ""),
        int(item.get("venue_order", 999)),
        item.get("title", "").lower(),
    )


def parse_local_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_event_datetimes(text: str, default_minutes: int = 60) -> tuple[str, str] | None:
    text = normalize_event_datetime_text(text)
    parsed_dates = parse_dates(text)
    if not parsed_dates:
        return None
    start_date = parsed_dates[0]
    end_date = parsed_dates[-1] if len(parsed_dates) > 1 else start_date
    time_range = parse_event_time_range(text)
    if not time_range:
        return None
    start_hour, start_minute, end_hour, end_minute = time_range
    start = datetime(start_date.year, start_date.month, start_date.day, start_hour, start_minute)
    if end_hour is None or end_minute is None:
        end = start + timedelta(minutes=default_minutes)
    else:
        end = datetime(end_date.year, end_date.month, end_date.day, end_hour, end_minute)
        if end <= start and end.date() == start.date():
            end += timedelta(hours=12)
    return start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")


def normalize_event_datetime_text(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\b([ap])\.m\.", r"\1m", value, flags=re.IGNORECASE)
    value = re.sub(r"\b([ap])\.m\b", r"\1m", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+ET\b", "", value)
    value = value.replace(" to ", " - ")
    return value


def parse_event_time_range(text: str) -> tuple[int, int, int | None, int | None] | None:
    text = normalize_event_datetime_text(text)
    range_match = re.search(
        r"(?<!\d)(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<a1>am|pm)?\s*[-–—]\s*"
        r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<a2>am|pm)\b",
        text,
        re.IGNORECASE,
    )
    if range_match:
        a1 = (range_match.group("a1") or range_match.group("a2")).lower()
        a2 = range_match.group("a2").lower()
        start = normalize_hour(int(range_match.group("h1")), int(range_match.group("m1") or 0), a1)
        end = normalize_hour(int(range_match.group("h2")), int(range_match.group("m2") or 0), a2)
        return start[0], start[1], end[0], end[1]

    single_match = re.search(
        r"(?<!\d)(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<a>am|pm)\b",
        text,
        re.IGNORECASE,
    )
    if not single_match:
        return None
    start = normalize_hour(int(single_match.group("h")), int(single_match.group("m") or 0), single_match.group("a").lower())
    return start[0], start[1], None, None


def normalize_hour(hour: int, minute: int, ampm: str) -> tuple[int, int]:
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def event_date_text_from_text(text: str) -> str:
    text = clean_text(text)
    matches = date_matches(text)
    if not matches:
        return text
    return text[matches[0].start() :]


def event_title_before_date(text: str) -> str:
    text = clean_text(text)
    matches = date_matches(text)
    if not matches:
        return clean_title(text)
    title = clean_title(text[: matches[0].start()])
    title = re.sub(r"\b(Learn More|View full event details here|Get your tickets today)$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(
        r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?,?$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    return title


def jewish_event_title_category(text: str) -> tuple[str, str]:
    before_date = event_title_before_date(text)
    for category in ["Classes & Workshops", "Talks & Performances", "Families", "Educators"]:
        if before_date.lower().startswith(category.lower()):
            return clean_title(before_date[len(category) :]), category
    return clean_title(before_date), ""


def extract_event_title(page: ParsedPage, venue_name: str, fallback: str) -> str:
    candidates = [
        page.meta.get("og:title", ""),
        page.meta.get("twitter:title", ""),
        page.headings[0] if page.headings else "",
        page.title,
        event_title_before_date(fallback),
    ]
    for candidate in candidates:
        title = strip_site_title(clean_title(candidate), venue_name)
        if title and not has_date_text(title):
            return title
    return clean_title(event_title_before_date(fallback))


def extract_event_date_text(source: dict[str, Any], page: ParsedPage, listing_text: str) -> str:
    raw = page.raw_html
    patterns = [
        r'field--name-field-display-date[^>]*field--item">(?P<value>.*?)</div>',
        r'field--name-field-display-date[^>]*>.*?field--item">(?P<value>.*?)</div>',
        r"<span>\s*When:\s*</span>\s*(?P<value>.*?)</div>",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE | re.DOTALL)
        if match:
            value = clean_date_text(strip_tags(match.group("value")))
            if value:
                return value

    sidebar_date = sidebar_widget_value(raw, "Date")
    sidebar_time = sidebar_widget_value(raw, "Time")
    if sidebar_date and sidebar_time:
        return clean_date_text(f"{sidebar_date} {sidebar_time}")

    for script in page.json_ld:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        for node in flatten_json_ld(data):
            type_text = " ".join(node.get("@type", [])) if isinstance(node.get("@type"), list) else str(node.get("@type", ""))
            if "Event" not in type_text:
                continue
            start = json_ld_local_datetime(str(node.get("startDate", "")))
            end = json_ld_local_datetime(str(node.get("endDate", "")))
            if start:
                start_dt = parse_local_datetime(start)
                end_dt = parse_local_datetime(end) if end else None
                if start_dt and end_dt:
                    return f"{format_date_label(start_dt.date().isoformat())} {format_time_label(start_dt)} - {format_time_label(end_dt)}"
                if start_dt:
                    return f"{format_date_label(start_dt.date().isoformat())} {format_time_label(start_dt)}"

    for chunk in page.chunks[:80]:
        if has_date_text(chunk) and parse_event_datetimes(chunk):
            return clean_date_text(chunk)
    return event_date_text_from_text(listing_text)


def json_ld_local_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.replace(tzinfo=None).isoformat(timespec="minutes")


def format_time_label(value: datetime) -> str:
    hour = value.hour
    minute = value.minute
    ampm = "PM" if hour >= 12 else "AM"
    display_hour = hour % 12 or 12
    if minute:
        return f"{display_hour}:{minute:02d} {ampm}"
    return f"{display_hour} {ampm}"


def sidebar_widget_value(raw_html: str, label: str) -> str:
    pattern = (
        rf'<div class="sidebar__widget-title">\s*{re.escape(label)}\s*</div>\s*'
        r'<div class="sidebar__widget-content">\s*(?P<value>.*?)</div>'
    )
    match = re.search(pattern, raw_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return clean_text(strip_tags(match.group("value")))


def extract_event_price_text(page: ParsedPage) -> str:
    raw = page.raw_html
    patterns = [
        r"<span>\s*Price:\s*</span>\s*(?P<value>.*?)</div>",
        r'field--name-field-tickets.*?<div class="field--label">Tickets</div>.*?<div class="field--item">(?P<value>.*?)</div>',
        r'field--name-field-tickets.*?<div class="field--item">(?P<value>.*?)</div>',
        r'events__event-ticket-price[^>]*>(?P<value>.*?)</span>',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE | re.DOTALL)
        if match:
            value = clean_text(strip_tags(match.group("value")))
            if value:
                return value
    for chunk in page.chunks[:55]:
        low = chunk.lower()
        if "$" in chunk or re.search(r"\bfree\b", low):
            if low.startswith("free friday nights"):
                continue
            if "discount available at checkout" in low:
                continue
            if any(
                phrase in low
                for phrase in [
                    "free priority admission",
                    "free or discounted tickets to museum programs",
                    "pre-sale opportunities",
                    "member preview",
                    "guest passes",
                    "special savings",
                    "join now",
                    "ability to purchase",
                ]
            ):
                continue
            if any(
                phrase in low
                for phrase in [
                    "membership",
                ]
            ) and "$" not in chunk:
                continue
            return clean_text(chunk)
    return ""


def parse_price_value(price_text: str) -> float | None:
    low = price_text.lower()
    if "free" in low and "$" not in price_text:
        return 0
    match = re.search(r"\$(?P<value>\d+(?:\.\d{1,2})?)", price_text)
    if not match:
        return None
    value = float(match.group("value"))
    return int(value) if value.is_integer() else value


def availability_text(value: str) -> str:
    low = value.lower()
    if "sold out" in low:
        return "Sold out"
    if "waitlist" in low or "join the waitlist" in low:
        return "Waitlist"
    if "tickets are required" in low:
        return "Tickets required"
    if "advance registration" in low or "registration required" in low:
        return "Registration required"
    return ""


def extract_event_location(source: dict[str, Any], page: ParsedPage) -> str:
    raw = page.raw_html
    address = sidebar_widget_value(raw, "Address")
    if address:
        return address.split(" New York")[0]
    for chunk in page.chunks[:60]:
        value = clean_location_text(chunk)
        if value and (value.lower() == "online" or value.lower().startswith("floor ") or "auditorium" in value.lower()):
            return value
    return source.get("location", source.get("name", ""))


def event_category(title: str, context: str = "") -> str:
    low = f"{title} {context}".lower()
    if "tour" in low or "gallery conversation" in low or "closer look" in low:
        return "Tours"
    if any(word in low for word in ["talk", "lecture", "panel", "conversation", "reading", "symposium"]):
        return "Talks"
    if any(word in low for word in ["concert", "performance", "music", "film", "dance", "cabaret"]):
        return "Performances"
    if any(word in low for word in ["family", "families", "kids", "children", "storytime"]):
        return "Family"
    if any(word in low for word in ["access", "asl", "captioning"]):
        return "Access"
    return "Events"


def format_display_date(status: str, start_iso: str | None, end_iso: str | None, raw_date_text: str) -> str:
    start_label = format_date_label(start_iso)
    end_label = format_date_label(end_iso)

    if status == "current" and end_label:
        return f"Through {end_label}"
    if status == "upcoming":
        if start_label and end_label:
            return f"Opens {start_label}; through {end_label}"
        if start_label:
            return f"Opens {start_label}"
        if end_label:
            return f"Through {end_label}"
    if end_label:
        return f"Through {end_label}"
    return raw_date_text or "Dates not listed"


def format_date_label(iso_date: str | None) -> str:
    if not iso_date:
        return ""
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return ""
    return f"{MONTH_LABELS[parsed.month]} {parsed.day}, {parsed.year}"


def extract_title(page: ParsedPage, venue_name: str, fallback: str) -> str:
    candidates = [
        page.meta.get("og:title", ""),
        page.meta.get("twitter:title", ""),
        page.headings[0] if page.headings else "",
        page.title,
        fallback,
    ]
    for candidate in candidates:
        if has_date_text(candidate):
            candidate = split_listing_title_date(candidate)[0]
        title = clean_title(candidate)
        title = strip_site_title(title, venue_name)
        if title and not is_bad_title(title, venue_name):
            return title
    return clean_title(fallback)


def strip_site_title(title: str, venue_name: str) -> str:
    pieces = re.split(r"\s+[|–—-]\s+", title)
    useful = [piece for piece in pieces if piece and venue_name.lower() not in piece.lower()]
    if useful:
        return clean_title(useful[0])
    return clean_title(title)


def extract_title_from_date_context(page: ParsedPage, venue_name: str) -> str:
    for chunk in page.chunks[:220]:
        if not has_date_text(chunk):
            continue
        title, date_text = split_listing_title_date(chunk)
        status, _start_iso, end_iso = classify_dates(date_text)
        if status not in {"current", "upcoming"} or not end_iso:
            continue
        if title and not is_bad_title(title, venue_name):
            return title
    return ""


def extract_date_text(page: ParsedPage, listing_context: str = "") -> str:
    candidates: list[tuple[int, str]] = []
    embedded_range = embedded_date_range_text(page.raw_html)
    if embedded_range:
        candidates.append((26, embedded_range))
    relative_end = relative_days_left_date_text(page.visible_text)
    if relative_end:
        candidates.append((24, relative_end))
    if listing_context:
        candidates.append((date_candidate_score(listing_context) + 4, listing_context))
    for key in ("event:start_time", "event:end_time", "article:published_time"):
        if page.meta.get(key):
            candidates.append((date_candidate_score(page.meta[key]), page.meta[key]))
    for key in ("description", "og:description", "twitter:description"):
        value = page.meta.get(key, "")
        score = date_candidate_score(value)
        if score > 0:
            candidates.append((score, value))
    for chunk in page.chunks[:220]:
        score = date_candidate_score(chunk)
        if score > 0:
            candidates.append((score, chunk))
    for snippet in raw_date_candidates(page.raw_html):
        score = date_candidate_score(snippet)
        if score > 0:
            candidates.append((score, snippet))

    cleaned = [(score, clean_date_text(extract_date_snippet(candidate))) for score, candidate in candidates]
    cleaned = [
        (score, candidate)
        for score, candidate in cleaned
        if candidate
        and candidate.lower() not in {"exhibitions", "current"}
        and has_date_text(candidate)
        and date_candidate_score(candidate) > 0
    ]
    if not cleaned:
        return ""
    cleaned.sort(key=date_candidate_sort_key)
    return cleaned[0][1][:180]


def relative_days_left_date_text(text: str) -> str:
    match = re.search(r"до окончания(?:\s+выставки)?\s*[—–-]\s*(?P<days>\d{1,4})\s*д", text or "", re.IGNORECASE)
    if not match:
        return ""
    end_date = date.today() + timedelta(days=int(match.group("days")))
    return f"Through {MONTH_LABELS[end_date.month]} {end_date.day}, {end_date.year}"


def embedded_date_range_text(raw_html: str) -> str:
    dates = re.findall(r'data-transform-date=["\'][^"\']*["\']>\s*(20\d{2}-\d{2}-\d{2})\s*<', raw_html or "")
    if len(dates) >= 2:
        return f"{dates[0]} - {dates[1]}"
    return ""


def date_candidate_sort_key(value: tuple[int, str]) -> tuple[int, int, int, int]:
    score, candidate = value
    status, _start_iso, end_iso = classify_dates(candidate)
    status_rank = {"current": 0, "upcoming": 0, "unknown": 2, "past": 3}.get(status, 2)
    finite_rank = 0 if end_iso else 1
    range_rank = 0 if len(date_matches(candidate)) >= 2 or re.search(r"\b(through|until|closes?)\b", candidate, re.IGNORECASE) else 1
    return (status_rank, finite_rank, range_rank, -score, len(candidate))


def raw_date_candidates(raw_html: str) -> list[str]:
    if not raw_html:
        return []
    text = strip_tags(raw_html)
    matches = date_matches(text)
    snippets: list[str] = []
    seen: set[str] = set()
    for match in matches[:80]:
        start = max(0, match.start() - 90)
        end = min(len(text), match.end() + 130)
        snippet = clean_date_text(extract_date_snippet(text[start:end]))
        if snippet and snippet not in seen:
            snippets.append(snippet)
            seen.add(snippet)
    return snippets


def split_listing_title_date(text: str) -> tuple[str, str]:
    text = clean_text(text)
    date_text = extract_date_snippet(text)
    title = text
    matches = date_matches(text)
    if matches:
        title = text[: matches[0].start()]
    elif re.search(r"\bongoing\b", text, re.IGNORECASE):
        match = re.search(r"\bongoing\b", text, re.IGNORECASE)
        if match:
            date_text = match.group(0)
            title = text[: match.start()]
    title = re.sub(r"^(Current|Upcoming)\s+Exhibition\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+Learn more\s*[›>].*$", "", title, flags=re.IGNORECASE)
    return clean_title(title), clean_date_text(date_text)


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return clean_text(value)


def date_candidate_score(text: str) -> int:
    text = clean_text(text)
    if not text:
        return 0
    low = text.lower()
    score = 0
    if DATE_MENTION_RE.search(text) or DAY_MONTH_MENTION_RE.search(text) or ISO_DATE_RE.search(text) or NUMERIC_DOT_DATE_RE.search(text):
        score += 4
    if re.search(r"\b(on view|through|until|opens?|opening|closes?|dates?|ongoing)\b", text, re.IGNORECASE):
        score += 6
    if re.match(r"^exhibition\.\s*", text, re.IGNORECASE):
        score += 5
    if re.search(r"\bmember previews?\b", text, re.IGNORECASE):
        score -= 8
    if re.search(r"\b\d{1,2}\s*[-:]\s*\d{1,2}\s*(am|pm)\b", text, re.IGNORECASE):
        score -= 2
    if any(word in low for word in ["updatedat", "createdat", "publishedat", "modifiedat", '"rank"', '"status"']):
        score -= 12
    if any(word in low for word in ["courtesy", "copyright", "©", "oil on", "ink on", "image courtesy", "archive"]):
        score -= 6
    if len(text) > 220:
        score -= 3
    return score


def extract_date_snippet(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    matches = date_matches(text)
    if not matches:
        keyword = re.search(r"\b(On view(?:\s+Online)?|Upcoming|Current|Ongoing|Opens?(?:\s+(?:soon|20\d{2}))?)\b", text, re.IGNORECASE)
        return keyword.group(0) if keyword else text

    start = matches[0].start()
    end = matches[-1].end()
    prefix = re.search(r"\b(On view|Through|Until|Opens?|Opening|Closes?)\s*$", text[:start], re.IGNORECASE)
    if prefix:
        start = prefix.start()

    # Include a connector between the last date mention and a trailing year when the first date omits it.
    trailing_year = re.match(r"^[\s,–—-]*(20\d{2}|19\d{2})\b", text[end:])
    if trailing_year:
        end += trailing_year.end()
    trailing_ongoing = re.match(r"^[\s,–—-]*(Ongoing)\b", text[end:], re.IGNORECASE)
    if trailing_ongoing:
        end += trailing_ongoing.end()

    snippet = text[start:end]
    snippet = re.sub(r"\s+Read more\b.*$", "", snippet, flags=re.IGNORECASE)
    return clean_date_text(snippet)


def date_matches(text: str) -> list[re.Match[str]]:
    raw_matches = sorted(
        [
            *DATE_MENTION_RE.finditer(text),
            *DAY_MONTH_MENTION_RE.finditer(text),
            *ISO_DATE_RE.finditer(text),
            *NUMERIC_DOT_DATE_RE.finditer(text),
        ],
        key=lambda match: (match.start(), -(match.end() - match.start())),
    )
    matches: list[re.Match[str]] = []
    last_end = -1
    for match in raw_matches:
        if match.start() < last_end:
            continue
        matches.append(match)
        last_end = match.end()
    return matches


def clean_date_text(text: str) -> str:
    text = clean_text(text)
    text = expand_numeric_dot_ranges(text)
    text = re.sub(r"^до\s+(?=\d)", "Through ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(On view|Dates?|Exhibition dates?)\s*:?\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(
        rf"\b(?P<day>\d{{1,2}})\s+de\s+(?P<month>{MONTH_RE})\s+\d{{1,2}}\s+de\s+(?P<year>\d{{4}})\b",
        r"\g<day> de \g<month> de \g<year>",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" .")


def has_date_text(text: str) -> bool:
    text = expand_numeric_dot_ranges(text)
    return bool(
        DATE_MENTION_RE.search(text)
        or DAY_MONTH_MENTION_RE.search(text)
        or ISO_DATE_RE.search(text)
        or NUMERIC_DOT_DATE_RE.search(text)
        or re.search(r"\bongoing\b", text, re.IGNORECASE)
    )


def has_displayable_date(item: dict[str, Any]) -> bool:
    raw_date_text = item.get("raw_date_text") or item.get("date_text") or ""
    if not item.get("end_date"):
        return False
    if re.search(r"\bongoing\b", raw_date_text, re.IGNORECASE):
        return False
    if re.search(r"\b(through|until|closes?)\b", raw_date_text, re.IGNORECASE):
        return bool(date_matches(raw_date_text))
    return len(date_matches(raw_date_text)) >= 2


def classify_dates(date_text: str, today: date | None = None) -> tuple[str, str | None, str | None]:
    today = today or date.today()
    explicit_year = bool(YEAR_RE.search(date_text))
    parsed = parse_dates(date_text)
    start = parsed[0] if parsed else None
    end = parsed[-1] if parsed else None
    is_ongoing = bool(re.search(r"\bongoing\b", date_text, re.IGNORECASE))

    if re.search(r"\b(through|until|closes?)\b", date_text, re.IGNORECASE) and len(parsed) == 1:
        start = None
        end = parsed[0]
        if end and not explicit_year and end < today:
            end = date(end.year + 1, end.month, end.day)
    if is_ongoing:
        end = None

    if start and end and start > end and len(parsed) == 2:
        start = date(start.year - 1, start.month, start.day)

    if start and today < start:
        status = "upcoming"
    elif end and today > end:
        status = "past"
    elif start or end or is_ongoing:
        status = "current"
    else:
        status = "unknown"

    return status, start.isoformat() if start else None, end.isoformat() if end else None


def parse_dates(text: str) -> list[date]:
    text = expand_numeric_dot_ranges(text)
    mentions: list[dict[str, int | None]] = []
    for match in date_matches(text):
        matched_text = match.group(0)
        if ISO_DATE_RE.fullmatch(matched_text):
            try:
                parsed = date.fromisoformat(matched_text)
            except ValueError:
                continue
            mentions.append({"month": parsed.month, "day": parsed.day, "year": parsed.year, "pos": match.start()})
            continue
        if NUMERIC_DOT_DATE_RE.fullmatch(matched_text):
            year = int(match.group("year"))
            if year < 100:
                year += 2000
            first = int(match.group("month"))
            second = int(match.group("day"))
            if len(match.group("year")) == 4 and second <= 12 and first > 12:
                month = second
                day = first
            elif len(match.group("year")) == 4 and second <= 12 and first <= 31:
                month = second
                day = first
            else:
                month = first
                day = second
            mentions.append(
                {
                    "month": month,
                    "day": day,
                    "year": year,
                    "pos": match.start(),
                }
            )
            continue
        month = MONTHS.get((match.groupdict().get("month") or "").lower().rstrip("."))
        day = int(match.groupdict().get("day") or 1)
        year_text = match.groupdict().get("year")
        year = int(year_text) if year_text else None
        if month:
            mentions.append({"month": month, "day": day, "year": year, "pos": match.start()})

    if not mentions:
        return []
    mentions.sort(key=lambda mention: int(mention["pos"] or 0))

    known_years = [mention["year"] for mention in mentions if mention["year"]]
    fallback_year = int(known_years[-1]) if known_years else date.today().year
    parsed: list[date] = []
    for index, mention in enumerate(mentions):
        year = mention["year"]
        if year is None:
            following = next((item["year"] for item in mentions[index + 1 :] if item["year"]), None)
            year = int(following or fallback_year)
        try:
            parsed.append(date(int(year), int(mention["month"] or 1), int(mention["day"] or 1)))
        except ValueError:
            continue
    return parsed


def expand_numeric_dot_ranges(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        year = match.group("year")
        first_a = int(match.group("day1"))
        first_b = int(match.group("month1"))
        second_a = int(match.group("day2"))
        second_b = int(match.group("month2"))
        us_style = len(year) == 2 or first_b > 12 or second_b > 12
        if us_style:
            month1, day1 = first_a, first_b
            month2, day2 = second_a, second_b
        else:
            day1, month1 = first_a, first_b
            day2, month2 = second_a, second_b
        if not (1 <= month1 <= 12 and 1 <= month2 <= 12 and 1 <= day1 <= 31 and 1 <= day2 <= 31):
            return match.group(0)
        if len(year) == 2:
            year = f"20{year}"
        first = f"{MONTH_LABELS[month1]} {day1}, {year}"
        second = f"{MONTH_LABELS[month2]} {day2}, {year}"
        return f"{first} - {second}"

    return NUMERIC_DOT_RANGE_RE.sub(repl, text or "")


def preferred_image(venue: dict[str, Any], page: ParsedPage) -> str:
    return venue_specific_image(venue, page) or best_image(page)


def venue_specific_image(venue: dict[str, Any], page: ParsedPage) -> str:
    name = venue.get("name", "")
    if name == "Galerie Gmurzynska":
        for src in page.images:
            image = absolutize_url(page.url, src)
            if is_gmurzynska_artwork_image(image):
                return image
    if name == "Krause Gallery":
        for src in page.images:
            image = normalize_wix_image(absolutize_url(page.url, src))
            if is_krause_artwork_image(image):
                return image
    if name == "Levy Gorvy Dayan":
        return levy_artwork_image(page)
    return ""


def first_image_from_html(block: str, page_url: str) -> str:
    for match in re.finditer(r"<img\b[^>]*>", block, re.IGNORECASE | re.DOTALL):
        image = image_from_img_tag(match.group(0), page_url)
        if is_useful_image(image):
            return image
    for image in image_urls_from_style(block, page_url):
        if is_useful_image(image):
            return image
    return ""


def first_href_from_html(block: str, page_url: str, required_path: str = "") -> str:
    for match in re.finditer(r'<a\b[^>]+href=["\'](?P<href>[^"\']+)["\']', block, re.IGNORECASE):
        href = absolutize_url(page_url, match.group("href"))
        href, _fragment = urldefrag(href)
        if required_path and required_path not in href.lower():
            continue
        return href
    return ""


def image_from_img_tag(tag: str, page_url: str) -> str:
    return image_from_img_attrs(html_attrs(tag), page_url)


def image_from_img_attrs(attrs: dict[str, str], page_url: str) -> str:
    for key in ("srcset", "data-srcset", "data-lazy-srcset"):
        if attrs.get(key):
            return best_src_from_srcset(attrs[key], page_url)
    for key in (
        "data-orig-file",
        "data-large-file",
        "data-medium-file",
        "data-original",
        "data-original-src",
        "data-image",
        "data-bg",
        "data-background",
        "data-lazy",
        "data-ll-src",
        "data-img",
        "data-src",
        "data-lazy-src",
        "src",
    ):
        if attrs.get(key):
            return absolutize_url(page_url, attrs[key])
    return ""


def image_urls_from_style(value: str, page_url: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"url\(\s*([\"']?)(?P<url>[^\"')]+)\1\s*\)", html.unescape(value or ""), re.IGNORECASE):
        url = clean_text(match.group("url"))
        if url:
            urls.append(absolutize_url(page_url, url))
    return urls


def html_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*([\"'])(.*?)\2", tag, re.DOTALL):
        attrs[match.group(1).lower()] = html.unescape(match.group(3))
    return attrs


def is_krause_artwork_image(url: str) -> bool:
    lower = url.lower()
    if not is_useful_image(url):
        return False
    if "static.wixstatic.com/media/9e36e8_" not in lower:
        return False
    if any(part in lower for part in ["logstretched", "w_34", "h_34", "w_49", "w_58", "w_192", "w_180", "w_32"]):
        return False
    return True


def is_gmurzynska_artwork_image(url: str) -> bool:
    lower = url.lower()
    if "static-assets.artlogic.net" not in lower:
        return False
    if "/exhibit-" not in lower:
        return False
    return is_useful_image(url)


def normalize_wix_image(url: str) -> str:
    if "static.wixstatic.com/media/" not in url or "/v1/" not in url:
        return url
    base, _transform = url.split("/v1/", 1)
    filename = url.rsplit("/", 1)[-1]
    return f"{base}/v1/fill/w_900,h_675,al_c,q_85,enc_auto/{filename}"


def levy_artwork_image(page: ParsedPage) -> str:
    artworks_index = page.raw_html.find('"artworks":[')
    if artworks_index == -1:
        return ""
    snippet = page.raw_html[artworks_index:]
    for match in re.finditer(r"image-([a-f0-9]+-\d+x\d+)-(jpg|jpeg|png|webp)", snippet, re.IGNORECASE):
        asset = match.group(1)
        extension = "jpg" if match.group(2).lower() == "jpeg" else match.group(2).lower()
        if not re.search(r"-(?:[7-9]\d{2,}|[1-9]\d{3,})x(?:[7-9]\d{2,}|[1-9]\d{3,})$", asset):
            continue
        return f"https://cdn.sanity.io/images/8uzch5mp/database/{asset}.{extension}?w=1200&h=900&fit=max&auto=format"
    return ""


def best_image(page: ParsedPage) -> str:
    for key in ("og:image", "twitter:image", "image"):
        if page.meta.get(key):
            image = absolutize_url(page.url, page.meta[key])
            if is_useful_image(image):
                return image
    for src in page.images:
        image = absolutize_url(page.url, src)
        if is_useful_image(image):
            return image
    for image in raw_image_candidates(page):
        if is_useful_image(image):
            return image
    return ""


def best_src_from_srcset(value: str, page_url: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if "," not in value:
        return absolutize_url(page_url, value)
    candidates: list[tuple[int, str]] = []
    for part in value.split(","):
        pieces = part.strip().split()
        if not pieces:
            continue
        width = 0
        if len(pieces) > 1 and pieces[1].endswith("w"):
            try:
                width = int(pieces[1][:-1])
            except ValueError:
                width = 0
        candidates.append((width, pieces[0]))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return absolutize_url(page_url, candidates[0][1])


def is_useful_image(url: str) -> bool:
    lower = (url or "").lower()
    if not lower:
        return False
    parsed = urlparse(lower)
    if any(host in parsed.netloc for host in ["mc.yandex", "google-analytics", "googletagmanager", "doubleclick", "facebook.com/tr"]):
        return False
    if "/watch/" in parsed.path or "/analytics" in parsed.path or "captcha.php" in parsed.path:
        return False
    if lower.startswith("data:"):
        return False
    if re.search(r"\.(?:svg|js|css|ico)(?:[?#]|$)", lower):
        return False
    bad_fragments = [
        "logo",
        "icon",
        "favicon",
        "placeholder",
        "blank.gif",
        "spacer.gif",
        "calendarcheck",
        "accessibility",
        "handshake",
        "suitcase",
        "adult_ic",
        "kids_ic",
        "nf-ic",
        "shildik",
        "right-anchor",
        "component_11",
        "frame_482817",
        "img_6879",
        "/80_80_",
        "/164_80_",
    ]
    if any(word in lower for word in bad_fragments):
        return False
    if re.search(r"(^|[/_-])1x1([._/?-]|$)", lower):
        return False
    return True


def raw_image_candidates(page: ParsedPage) -> list[str]:
    text = html.unescape(page.raw_html or "")
    candidates: list[str] = []
    patterns = [
        r"https?://[^\"'()\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'()\s<>]*)?",
        r"/(?:upload|uploads|files|images|img|media|sites|wp-content)/[^\"'()\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'()\s<>]*)?",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            image = absolutize_url(page.url, match.group(0).rstrip("\\"))
            if image not in candidates:
                candidates.append(image)
    return candidates


def image_from_value(value: Any, page_url: str) -> str:
    if isinstance(value, str):
        image = absolutize_url(page_url, value)
        return image if is_useful_image(image) else ""
    if isinstance(value, list) and value:
        for item in value:
            image = image_from_value(item, page_url)
            if image:
                return image
        return ""
    if isinstance(value, dict):
        for key in ("url", "src", "sourceUrl"):
            image = image_from_value(value.get(key), page_url)
            if image:
                return image
    return ""


def is_relevant_location(venue: dict[str, Any], item: dict[str, Any], text: str) -> bool:
    location_includes = [str(keyword).lower() for keyword in venue.get("location_include_keywords", [])]
    location_excludes = [str(keyword).lower() for keyword in venue.get("location_exclude_keywords", [])]
    if location_includes or location_excludes:
        focused = " ".join([item["title"], item["location"], item["source_url"]]).lower()
        if location_excludes and any(keyword in focused for keyword in location_excludes):
            return False
        if location_includes:
            return any(keyword in focused for keyword in location_includes)
        return True
    haystack = " ".join([item["title"], item["location"], item["source_url"], text[:3000]]).lower()
    return is_relevant_location_text(venue, haystack)


def is_relevant_location_text(venue: dict[str, Any], text: str) -> bool:
    haystack = text.lower()
    location_excludes = [str(keyword).lower() for keyword in venue.get("location_exclude_keywords", [])]
    if any(keyword in haystack for keyword in location_excludes):
        return False
    location_includes = [str(keyword).lower() for keyword in venue.get("location_include_keywords", [])]
    if location_includes and not any(keyword in haystack for keyword in location_includes):
        return False
    if not venue.get("nyc_only"):
        return True
    if venue.get("name") == "Levy Gorvy Dayan":
        locations = re.findall(r"lévy gorvy dayan\s*,?\s*(new york|nyc|london|paris|hong kong)\b", haystack)
        if locations:
            return locations[0] in {"new york", "nyc"}
    reject = ["zurich", "zürich", "london", "hong kong", "los angeles", "monaco", "paris", "basel", "st. moritz"]
    accept = ["new york", "nyc", "18th street", "chelsea", "madison avenue", "upper east side"]
    if any(word in haystack for word in accept):
        return True
    return not any(word in haystack for word in reject)


def has_forbidden_listing_text(venue: dict[str, Any], text: str) -> bool:
    haystack = (text or "").lower()
    rejects = venue.get("exclude_text_keywords", [])
    return any(str(keyword).lower() in haystack for keyword in rejects)


def link_has_past_dates(text: str) -> bool:
    if not has_date_text(text):
        return False
    return classify_dates(text)[0] == "past"


def is_bad_title(title: str, venue_name: str) -> bool:
    low = title.lower()
    bad_exact = {
        "",
        "exhibitions",
        "current",
        "current exhibit",
        "current exhibition",
        "upcoming",
        "current exhibitions",
        "upcoming exhibitions",
        "past exhibitions",
        "visit",
        "events",
        "calendar",
        "tickets",
        "learn more",
        "read more",
        "add to collection",
        "main navigation",
        "javascript is disabled",
        "exhibition archive",
        "exhibits archive",
        "archive",
        "past",
        "forthcoming",
        "previous exhibitions",
        "en exhibición",
        "en exhibicion",
        "exposiciones",
        "exposiciones anteriores",
        "próximamente",
        "proximamente",
        "traveling exhibitions",
        "highlights of work:",
        "performance",
        "performance upcoming and past",
        "contemporary & modern art gallery",
    }
    if low in bad_exact:
        return True
    if len(title) < 3 or len(title) > 160:
        return True
    if low == venue_name.lower():
        return True
    if low.replace(" ", "") == venue_name.lower().replace(" ", ""):
        return True
    if low.endswith(" archive") or low.startswith("archive "):
        return True
    if low.startswith("opening reception"):
        return True
    if "upcoming and past" in low:
        return True
    return False


def dedupe_exhibitions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = "|".join([item.get("venue", ""), item.get("title", "").lower(), item.get("date_text", "")])
        existing = deduped.get(key)
        if not existing:
            deduped[key] = item
            continue
        if item.get("source_is_detail") and not existing.get("source_is_detail"):
            deduped[key] = item
        elif item.get("image_url") and not existing.get("image_url"):
            deduped[key] = item
    return list(deduped.values())


def sort_key(item: dict[str, Any]) -> tuple[str, int, str, int, str, str]:
    status_rank = "0" if item.get("status") == "current" else "1"
    return (
        item.get("city", ""),
        int(item.get("tab_order", 999)),
        status_rank,
        int(item.get("venue_order", 999)),
        item.get("start_date") or "9999-99-99",
        item.get("title", "").lower(),
    )


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_title(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\s*[\n\r]\s*", " ", value)
    value = re.sub(r"\s+\bON\s+VIEW\b$", "", value, flags=re.IGNORECASE)
    value = value.strip(" -|")
    return humanize_all_caps_title(value)


def humanize_all_caps_title(title: str) -> str:
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", title)
    if not letters or any(char.islower() for char in letters):
        return title

    small_words = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}
    words = re.split(r"(\s+)", title.lower())
    styled: list[str] = []
    word_index = 0
    capitalize_next = True
    for word in words:
        if not word or word.isspace():
            styled.append(word)
            continue
        pieces = re.split(r"([-/:])", word)
        styled_pieces: list[str] = []
        for piece in pieces:
            if not piece:
                continue
            if piece in {"-", "/", ":"}:
                styled_pieces.append(piece)
                if piece == ":":
                    capitalize_next = True
            elif piece in small_words and word_index > 0:
                styled_pieces.append(piece[:1].upper() + piece[1:] if capitalize_next else piece)
                capitalize_next = False
            else:
                styled_pieces.append(piece[:1].upper() + piece[1:])
                capitalize_next = False
        styled.append("".join(styled_pieces))
        word_index += 1
    return "".join(styled)


def absolutize_url(base_url: str, href: str) -> str:
    return urljoin(base_url, html.unescape(href or ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh SeeArt exhibition and event caches.")
    parser.add_argument("--debug-venue", help="Print candidate links for one venue and exit.")
    parser.add_argument("--debug-chunks", action="store_true", help="Include parsed text chunks with --debug-venue.")
    parser.add_argument("--exhibitions-only", action="store_true", help="Refresh only the exhibition cache.")
    parser.add_argument("--events-only", action="store_true", help="Refresh only the event cache.")
    args = parser.parse_args()
    if args.debug_venue:
        debug_venue(args.debug_venue, include_chunks=args.debug_chunks)
        return

    if args.events_only:
        payload = run_event_scrape()
        print(json.dumps({"generated_at": payload["generated_at"], "event_count": len(payload["events"]), "errors": payload["errors"]}, indent=2))
        return
    if args.exhibitions_only:
        payload = run_scrape()
        print(json.dumps({"generated_at": payload["generated_at"], "exhibition_count": len(payload["exhibitions"]), "errors": payload["errors"]}, indent=2))
        return

    payload = run_all_scrapes()
    print(
        json.dumps(
            {
                "generated_at": payload["generated_at"],
                "exhibition_count": len(payload["exhibitions"]["exhibitions"]),
                "event_count": len(payload["events"]["events"]),
                "exhibition_errors": payload["exhibitions"]["errors"],
                "event_errors": payload["events"]["errors"],
            },
            indent=2,
        )
    )


def debug_venue(name: str, include_chunks: bool = False) -> None:
    config = read_config()
    venue = next((item for item in config["venues"] if name.lower() in item["name"].lower()), None)
    if not venue:
        raise SystemExit(f"No venue matching {name!r}")
    page = fetch_page(venue["url"])
    print(f"{venue['name']} links from {venue['url']}")
    for index, (href, text) in enumerate(candidate_links(venue, page)[:40], 1):
        print(f"{index:02d}. {text} | {href}")
    if include_chunks:
        print("\nChunks")
        for index, chunk in enumerate(page.chunks[:120], 1):
            print(f"{index:03d}. {chunk}")


if __name__ == "__main__":
    main()
