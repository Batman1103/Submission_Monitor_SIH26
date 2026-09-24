import re
import subprocess
from typing import Optional

from bs4 import BeautifulSoup

SOURCE_URL = "https://www.sih.gov.in/sih2026PS"


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_count(value: str):
    m = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", value or "")
    if not m:
        return None, None

    return (
        int(m.group(1).replace(",", "")),
        int(m.group(2).replace(",", "")),
    )


def normalize_header(value: str) -> str:
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return value


def header_index(headers: list[str], *names: str) -> Optional[int]:
    wanted = {normalize_header(name) for name in names}

    for i, header in enumerate(headers):
        if normalize_header(header) in wanted:
            return i

    return None


def fetch_html() -> str:
    """
    Fetch SIH using curl instead of requests.

    SIH/WAF can reject Python requests based on the HTTP/TLS
    fingerprint. curl with browser-like headers works more reliably.
    """

    command = [
        "curl",
        "-sS",
        "-L",
        "--compressed",
        "--max-time",
        "90",

        "-H",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",

        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",

        "-H",
        "Accept-Language: en-US,en;q=0.9",

        "-H",
        "Referer: https://www.sih.gov.in/",

        "-H",
        "Sec-Fetch-Dest: document",

        "-H",
        "Sec-Fetch-Mode: navigate",

        "-H",
        "Sec-Fetch-Site: same-origin",

        "-H",
        'Sec-Ch-Ua: "Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="99"',

        "-H",
        "Sec-Ch-Ua-Mobile: ?0",

        "-H",
        'Sec-Ch-Ua-Platform: "Windows"',

        SOURCE_URL,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        timeout=120,
    )

    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"curl failed with exit code {result.returncode}: {error}"
        )

    html = result.stdout.decode("utf-8", errors="replace")

    if not html.strip():
        raise RuntimeError("SIH returned an empty response")

    if "dataTablePS" not in html and "<table" not in html:
        raise RuntimeError(
            "SIH response does not contain the expected problem-statement table"
        )

    return html


def fetch_problem_statements():

    html = fetch_html()

    soup = BeautifulSoup(html, "html.parser")

    records = []

    for table in soup.find_all("table"):

        header_row = table.find("tr")

        if not header_row:
            continue

        headers = [
            clean(c.get_text(" ", strip=True))
            for c in header_row.find_all(["th", "td"])
        ]

        normalized = {normalize_header(h) for h in headers}

        required = {
            "organization",
            "problem statement title",
            "category",
            "ps number",
            "submitted idea s count",
            "theme",
            "deadline for idea submission",
        }

        if not required.issubset(normalized):
            continue

        idx_org = header_index(headers, "Organization")
        idx_title = header_index(headers, "Problem Statement Title")
        idx_category = header_index(headers, "Category")
        idx_ps = header_index(headers, "PS Number")
        idx_count = header_index(headers, "Submitted Idea(s) Count")
        idx_theme = header_index(headers, "Theme")
        idx_deadline = header_index(
            headers,
            "Deadline for Idea Submission"
        )

        indexes = [
            idx_org,
            idx_title,
            idx_category,
            idx_ps,
            idx_count,
            idx_theme,
            idx_deadline,
        ]

        if any(i is None for i in indexes):
            continue

        rows = table.find_all("tr")

        for tr in rows[1:]:

            cells = tr.find_all("td")

            values = [
                clean(c.get_text(" ", strip=True))
                for c in cells
            ]

            if len(values) <= max(indexes):
                continue

            ps_id = values[idx_ps]

            if not re.fullmatch(r"SIH\d{5,}", ps_id):
                continue

            category = values[idx_category].capitalize()

            if category not in ("Software", "Hardware"):
                continue

            submitted, capacity = parse_count(
                values[idx_count]
            )

            if submitted is None or capacity is None:
                continue

            records.append(
                {
                    "ps_id": ps_id,
                    "title": values[idx_title],
                    "organization": values[idx_org],
                    "department": "",
                    "category": category,
                    "theme": values[idx_theme],
                    "submitted": submitted,
                    "capacity": capacity,
                    "deadline": values[idx_deadline],
                    "description": "",
                }
            )

        if records:
            break

    unique = {}

    for record in records:
        unique[record["ps_id"]] = record

    return list(unique.values())