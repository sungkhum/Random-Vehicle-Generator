from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from lxml import html
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
USER_AGENT = "CodexVehicleGenerator/1.0 (https://openai.com)"
DATE_CLAIM_PROPERTIES = (
    ("P2031", "work period (start)"),
    ("P606", "first flight"),
    ("P729", "service entry"),
    ("P571", "inception"),
    ("P580", "start time"),
    ("P577", "publication date"),
)
ERA_BUCKETS = (
    {
        "id": "before-1946",
        "label": "Before 1946",
        "description": "Early and wartime vehicles",
        "start": None,
        "end": 1945,
    },
    {
        "id": "1946-1969",
        "label": "1946-1969",
        "description": "Post-war and early jet age",
        "start": 1946,
        "end": 1969,
    },
    {
        "id": "1970-1999",
        "label": "1970-1999",
        "description": "Late 20th century vehicles",
        "start": 1970,
        "end": 1999,
    },
    {
        "id": "2000-and-newer",
        "label": "2000 and newer",
        "description": "Contemporary vehicles",
        "start": 2000,
        "end": None,
    },
    {
        "id": "unknown-age",
        "label": "Unknown age",
        "description": "No reliable year found yet",
        "start": None,
        "end": None,
        "unknown": True,
    },
)


def fetch_json(url: str, accept: str | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def normalize_wiki_title(value: str) -> str:
    return normalize_text(urllib.parse.unquote(value).replace("_", " "))


def wikipedia_article_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
        title.replace(" ", "_")
    )


def commons_file_url(file_name: str) -> str:
    return "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
        file_name.replace(" ", "_")
    )


def wikipedia_root(page: str) -> html.HtmlElement:
    url = (
        "https://en.wikipedia.org/w/api.php?action=parse"
        f"&page={urllib.parse.quote(page)}&prop=text&formatversion=2&format=json"
    )
    payload = fetch_json(url)
    return html.fromstring(payload["parse"]["text"])


def wikipedia_category_titles(category_title: str) -> list[str]:
    titles: list[str] = []
    cmcontinue: str | None = None

    while True:
      url = (
          "https://en.wikipedia.org/w/api.php?action=query&list=categorymembers"
          f"&cmtitle={urllib.parse.quote('Category:' + category_title)}"
          "&cmtype=page&cmlimit=500&format=json"
      )
      if cmcontinue:
          url += f"&cmcontinue={urllib.parse.quote(cmcontinue)}"

      payload = fetch_json(url)
      titles.extend(
          member["title"] for member in payload.get("query", {}).get("categorymembers", [])
      )

      cmcontinue = payload.get("continue", {}).get("cmcontinue")
      if not cmcontinue:
          break

    return titles


def cell_wiki_title(cell: html.HtmlElement) -> str:
    for anchor in cell.xpath('.//a[@href]'):
        href = anchor.get("href", "")
        if not href.startswith("/wiki/"):
            continue
        target = href.removeprefix("/wiki/")
        if not target or ":" in target:
            continue
        return normalize_wiki_title(target)
    return ""


def table_names(
    *,
    page: str,
    name_parts: list[int],
    table_indices: list[int] | str = "all",
    skip_exact: set[str] | None = None,
    skip_if_contains: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[dict]:
    root = wikipedia_root(page)
    tables = root.xpath('//table[contains(@class, "wikitable")]')
    indices = range(len(tables)) if table_indices == "all" else table_indices
    items: list[dict] = []
    seen: set[str] = set()
    skip_exact = skip_exact or set()

    for table_index in indices:
        table = tables[table_index]
        for row in table.xpath(".//tr[position()>1]"):
            cell_nodes = row.xpath("./th|./td")
            cells = [normalize_text(" ".join(cell.itertext())) for cell in cell_nodes]
            if not cell_nodes:
                continue

            parts = [cells[index] for index in name_parts if index < len(cells)]
            name = normalize_text(" ".join(part for part in parts if part))
            lowered = name.casefold()
            wiki_title = ""
            for index in reversed(name_parts):
                if index < len(cell_nodes):
                    wiki_title = cell_wiki_title(cell_nodes[index])
                    if wiki_title:
                        break

            if not name or name in skip_exact:
                continue
            if any(fragment in lowered for fragment in skip_if_contains):
                continue
            if lowered in seen:
                continue

            seen.add(lowered)
            item = {"name": name}
            if wiki_title:
                item["wikiTitle"] = wiki_title
            items.append(item)

            if limit and len(items) >= limit:
                return items

    return items


def category_names(
    *,
    category_titles: list[str],
    skip_exact: set[str] | None = None,
    skip_if_contains: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    skip_exact = skip_exact or set()

    for category_title in category_titles:
        for name in wikipedia_category_titles(category_title):
            normalized_name = normalize_text(name)
            lowered = normalized_name.casefold()

            if not normalized_name or normalized_name in skip_exact:
                continue
            if any(fragment in lowered for fragment in skip_if_contains):
                continue
            if lowered in seen:
                continue

            seen.add(lowered)
            items.append({"name": normalized_name, "wikiTitle": normalized_name})

            if limit and len(items) >= limit:
                return items

    return items


def wikidata_family_items(
    *,
    category_qid: str,
    model_qid: str,
    limit: int,
    label_contains_any: tuple[str, ...] = (),
    description_contains_any: tuple[str, ...] = (),
) -> list[dict]:
    query = f"""
PREFIX schema: <http://schema.org/>
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?article WHERE {{
  ?item wdt:P31 wd:{model_qid} .
  ?item wdt:P279* wd:{category_qid} .
  OPTIONAL {{
    ?article schema:about ?item ;
      schema:isPartOf <https://en.wikipedia.org/> .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT {limit}
""".strip()
    url = (
        "https://query.wikidata.org/sparql?format=json&query="
        + urllib.parse.quote(query)
    )
    payload = fetch_json(url, "application/sparql-results+json")

    items: list[dict] = []
    seen: set[str] = set()
    for row in payload["results"]["bindings"]:
        label = normalize_text(row["itemLabel"]["value"])
        if re.fullmatch(r"Q\d+", label):
            continue

        description = normalize_text(row.get("itemDescription", {}).get("value", ""))
        lowered_label = label.casefold()
        lowered_description = description.casefold()

        if label_contains_any and not any(
            fragment in lowered_label for fragment in label_contains_any
        ):
            continue
        if description_contains_any and not any(
            fragment in lowered_description for fragment in description_contains_any
        ):
            continue

        if lowered_label in seen:
            continue

        seen.add(lowered_label)
        item = {
            "name": label,
            "description": description,
        }
        article = row.get("article", {}).get("value")
        if article:
            item["wikiTitle"] = normalize_wiki_title(urlparse(article).path.split("/")[-1])
        items.append(item)

    return items


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def extract_claim_year(claim: dict) -> int | None:
    mainsnak = claim.get("mainsnak", {})
    datavalue = mainsnak.get("datavalue", {})
    value = datavalue.get("value")
    if not isinstance(value, dict):
        return None

    time_value = value.get("time")
    precision = value.get("precision", 0)
    if not isinstance(time_value, str) or precision < 9:
        return None

    match = re.match(r"([+-])(\d+)-", time_value)
    if not match:
        return None

    year = int(match.group(2))
    if match.group(1) == "-":
        year *= -1
    return year


def era_for_year(year: int | None) -> dict:
    if year is None:
        return next(bucket for bucket in ERA_BUCKETS if bucket.get("unknown"))

    for bucket in ERA_BUCKETS:
        if bucket.get("unknown"):
            continue
        start = bucket["start"]
        end = bucket["end"]
        if (start is None or year >= start) and (end is None or year <= end):
            return bucket

    return next(bucket for bucket in ERA_BUCKETS if bucket.get("unknown"))


def fetch_page_images(vehicles: list[dict]) -> None:
    title_to_records: dict[str, list[dict]] = defaultdict(list)
    requested_titles: list[str] = []
    seen_titles: set[str] = set()

    for vehicle in vehicles:
        lookup_title = vehicle.get("wikiTitle") or vehicle["name"]
        vehicle["wikiTitle"] = lookup_title
        lowered = lookup_title.casefold()
        title_to_records[lowered].append(vehicle)
        if lowered not in seen_titles:
            seen_titles.add(lowered)
            requested_titles.append(lookup_title)

    for batch in chunked(requested_titles, 40):
        params = {
            "action": "query",
            "format": "json",
            "prop": "pageimages|pageprops",
            "piprop": "thumbnail|original|name",
            "pithumbsize": "900",
            "redirects": "1",
            "titles": "|".join(batch),
        }
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            params, safe="|"
        )
        payload = fetch_json(url)

        alias_map = {title: title for title in batch}
        for mapping in payload.get("query", {}).get("normalized", []):
            alias_map[mapping["from"]] = mapping["to"]
        for mapping in payload.get("query", {}).get("redirects", []):
            source = alias_map.get(mapping["from"], mapping["from"])
            alias_map[mapping["from"]] = mapping["to"]
            alias_map[source] = mapping["to"]

        pages_by_title = {
            page.get("title"): page for page in payload.get("query", {}).get("pages", {}).values()
        }

        for requested_title in batch:
            resolved_title = alias_map.get(requested_title, requested_title)
            page = pages_by_title.get(resolved_title)
            if not page or "missing" in page:
                continue

            thumbnail = page.get("thumbnail", {}).get("source")
            original = page.get("original", {}).get("source")
            image_name = page.get("pageimage")
            wikidata_id = page.get("pageprops", {}).get("wikibase_item")
            if not thumbnail and not original:
                image = None
            else:
                image = {
                    "thumbnailUrl": thumbnail or original,
                    "originalUrl": original or thumbnail,
                    "articleTitle": resolved_title,
                    "articleUrl": wikipedia_article_url(resolved_title),
                }
                if image_name:
                    image["fileName"] = image_name
                    image["filePageUrl"] = commons_file_url(f"File:{image_name}")

            for vehicle in title_to_records[requested_title.casefold()]:
                vehicle["wikiTitle"] = resolved_title
                if image:
                    vehicle["image"] = image
                if wikidata_id:
                    vehicle["wikidataId"] = wikidata_id


def fetch_vehicle_years(vehicles: list[dict]) -> None:
    qid_to_records: dict[str, list[dict]] = defaultdict(list)
    unique_qids: list[str] = []
    seen_qids: set[str] = set()

    for vehicle in vehicles:
        qid = vehicle.get("wikidataId")
        if not qid:
            continue
        qid_to_records[qid].append(vehicle)
        if qid not in seen_qids:
            seen_qids.add(qid)
            unique_qids.append(qid)

    for batch in chunked(unique_qids, 50):
        params = {
            "action": "wbgetentities",
            "format": "json",
            "props": "claims",
            "ids": "|".join(batch),
        }
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            params, safe="|"
        )
        payload = fetch_json(url)

        for qid in batch:
            entity = payload.get("entities", {}).get(qid, {})
            claims = entity.get("claims", {})
            candidate_years: list[tuple[int, str]] = []

            for property_id, label in DATE_CLAIM_PROPERTIES:
                for claim in claims.get(property_id, []):
                    year = extract_claim_year(claim)
                    if year is None:
                        continue
                    candidate_years.append((year, label))

            if not candidate_years:
                continue

            year, source = min(candidate_years, key=lambda item: item[0])
            for vehicle in qid_to_records[qid]:
                vehicle["year"] = year
                vehicle["yearSource"] = source


def build_era_records(vehicles: list[dict]) -> list[dict]:
    counts = defaultdict(int)

    for vehicle in vehicles:
        era = era_for_year(vehicle.get("year"))
        vehicle["eraId"] = era["id"]
        counts[era["id"]] += 1

    return [
        {
            "id": bucket["id"],
            "label": bucket["label"],
            "description": bucket["description"],
            "count": counts[bucket["id"]],
        }
        for bucket in ERA_BUCKETS
    ]


CATEGORIES = [
    {
        "id": "fighter-jets",
        "label": "Fighter Jets",
        "group": "Air",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q14405627",
        "sourceType": "wikidata",
        "categoryQid": "Q14405627",
        "modelQid": "Q15056993",
        "limit": 180,
    },
    {
        "id": "bombers",
        "label": "Bombers",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_bomber_aircraft",
        "sourceType": "table",
        "page": "List of bomber aircraft",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 220,
    },
    {
        "id": "attack-aircraft",
        "label": "Attack Aircraft",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_attack_aircraft",
        "sourceType": "table",
        "page": "List of attack aircraft",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 220,
    },
    {
        "id": "military-transports",
        "label": "Military Transports",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_military_transport_aircraft",
        "sourceType": "table",
        "page": "List of military transport aircraft",
        "tableIndices": "all",
        "nameParts": [0],
        "limit": 260,
    },
    {
        "id": "airliners",
        "label": "Airliners",
        "group": "Air",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_commercial_jet_airliners",
        "sourceType": "table",
        "page": "List of commercial jet airliners",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 160,
    },
    {
        "id": "helicopters",
        "label": "Helicopters",
        "group": "Air",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q34486",
        "sourceType": "wikidata",
        "categoryQid": "Q34486",
        "modelQid": "Q15056993",
        "limit": 180,
    },
    {
        "id": "attack-helicopters",
        "label": "Attack Helicopters",
        "group": "Air",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Attack_helicopters",
        "sourceType": "category",
        "categoryTitles": ["Attack helicopters"],
        "skipExact": {
            "Advanced Attack Helicopter",
            "Attack helicopter",
            "List of military rotorcraft in production and in development by the European defence industry",
        },
        "limit": 120,
    },
    {
        "id": "tanks",
        "label": "Tanks",
        "group": "Land",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_main_battle_tanks_by_generation",
        "sourceType": "table",
        "page": "List of main battle tanks by generation",
        "tableIndices": [0],
        "nameParts": [0],
        "limit": 220,
    },
    {
        "id": "tank-destroyers",
        "label": "Tank Destroyers",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Tank_destroyers",
        "sourceType": "category",
        "categoryTitles": ["Tank destroyers"],
        "skipExact": {
            "Tank destroyer",
            "Anti-tank missile carrier",
            "Missile tank",
            "Self-propelled anti-tank gun",
        },
        "limit": 120,
    },
    {
        "id": "apcs",
        "label": "Armored Personnel Carriers",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Armoured_personnel_carriers",
        "sourceType": "category",
        "categoryTitles": ["Armoured personnel carriers"],
        "skipExact": {"Armoured personnel carrier"},
        "skipContains": ("list of",),
        "limit": 180,
    },
    {
        "id": "ifvs",
        "label": "Infantry Fighting Vehicles",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Infantry_fighting_vehicles",
        "sourceType": "category",
        "categoryTitles": ["Infantry fighting vehicles"],
        "skipExact": {"Infantry fighting vehicle"},
        "skipContains": ("list of",),
        "limit": 180,
    },
    {
        "id": "recon-vehicles",
        "label": "Recon Vehicles",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Reconnaissance_vehicles",
        "sourceType": "category",
        "categoryTitles": ["Reconnaissance vehicles"],
        "skipExact": {"Reconnaissance vehicle", "Scout car"},
        "limit": 180,
    },
    {
        "id": "mraps",
        "label": "MRAPs",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Mine-resistant_ambush_protected_vehicles",
        "sourceType": "category",
        "categoryTitles": ["Mine-resistant ambush protected vehicles"],
        "limit": 180,
    },
    {
        "id": "armored-cars",
        "label": "Armored Cars",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Armoured_cars",
        "sourceType": "category",
        "categoryTitles": ["Armoured cars"],
        "skipExact": {
            "Armored car (military)",
            "Non-military armoured vehicle",
            "Police armored vehicle",
            "Light armoured vehicle",
        },
        "skipContains": ("list of", "company"),
        "limit": 220,
    },
    {
        "id": "rocket-artillery",
        "label": "Rocket Artillery",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Multiple_rocket_launchers",
        "sourceType": "category",
        "categoryTitles": ["Multiple rocket launchers"],
        "skipExact": {"Multiple rocket launcher"},
        "skipContains": ("list of", "rocket-bombs"),
        "limit": 180,
    },
    {
        "id": "self-propelled-artillery",
        "label": "Self-Propelled Artillery",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Self-propelled_artillery",
        "sourceType": "category",
        "categoryTitles": [
            "Self-propelled artillery of the Soviet Union",
            "Self-propelled artillery of the United States",
            "Self-propelled artillery of Germany",
        ],
        "skipExact": {"Samokhodnaya Ustanovka"},
        "limit": 180,
    },
    {
        "id": "amphibious-assault-vehicles",
        "label": "Amphibious Assault Vehicles",
        "group": "Land",
        "sourceLabel": "Wikipedia Category",
        "sourceUrl": "https://en.wikipedia.org/wiki/Category:Amphibious_armoured_personnel_carriers",
        "sourceType": "category",
        "categoryTitles": [
            "Amphibious armoured personnel carriers",
            "Amphibious armoured fighting vehicles",
        ],
        "skipExact": {
            "Abbot (artillery)",
            "Amphibious armoured fighting vehicle",
            "FV180 Combat Engineer Tractor",
            "FV434",
            "Template:Tanks converted to armored vehicles",
        },
        "skipContains": ("list of",),
        "limit": 220,
    },
    {
        "id": "sports-cars",
        "label": "Sports Cars",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_sports_cars",
        "sourceType": "table",
        "page": "List of sports cars",
        "tableIndices": [0],
        "nameParts": [0, 1],
        "limit": 700,
    },
    {
        "id": "supercars",
        "label": "Supercars",
        "group": "Road",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q815679",
        "sourceType": "wikidata",
        "categoryQid": "Q815679",
        "modelQid": "Q3231690",
        "limit": 220,
    },
    {
        "id": "race-cars",
        "label": "Race Cars",
        "group": "Road",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q673687",
        "sourceType": "wikidata",
        "categoryQid": "Q673687",
        "modelQid": "Q90834785",
        "limit": 220,
    },
    {
        "id": "muscle-cars",
        "label": "Muscle Cars",
        "group": "Road",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q1072763",
        "sourceType": "wikidata",
        "categoryQid": "Q1072763",
        "modelQid": "Q3231690",
        "limit": 140,
    },
    {
        "id": "pickup-trucks",
        "label": "Pickup Trucks",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_pickup_trucks",
        "sourceType": "table",
        "page": "List of pickup trucks",
        "tableIndices": "all",
        "nameParts": [0, 1],
        "limit": 320,
    },
    {
        "id": "suvs",
        "label": "SUVs",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_sport_utility_vehicles",
        "sourceType": "table",
        "page": "List of sport utility vehicles",
        "tableIndices": "all",
        "nameParts": [0, 1],
        "limit": 420,
    },
    {
        "id": "buses",
        "label": "Buses",
        "group": "Road",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_buses",
        "sourceType": "table",
        "page": "List of buses",
        "tableIndices": "all",
        "nameParts": [3, 0],
        "limit": 320,
        "skipExact": {"Manufacturer Bus", "Bus"},
    },
    {
        "id": "locomotives",
        "label": "Locomotives",
        "group": "Rail",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q93301",
        "sourceType": "wikidata",
        "categoryQid": "Q93301",
        "modelQid": "Q19832486",
        "limit": 200,
    },
    {
        "id": "high-speed-trains",
        "label": "High-Speed Trains",
        "group": "Rail",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_high-speed_trains",
        "sourceType": "table",
        "page": "List of high-speed trains",
        "tableIndices": "all",
        "nameParts": [0],
        "skipExact": {"Operated", "Designed", "Record", "Name"},
        "limit": 220,
    },
    {
        "id": "sailboats",
        "label": "Sailboats",
        "group": "Sea",
        "sourceLabel": "Wikipedia List",
        "sourceUrl": "https://en.wikipedia.org/wiki/List_of_sailing_boat_types",
        "sourceType": "table",
        "page": "List of sailing boat types",
        "tableIndices": "all",
        "nameParts": [0],
        "limit": 260,
    },
    {
        "id": "submarines",
        "label": "Submarines",
        "group": "Sea",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q2811",
        "sourceType": "wikidata",
        "categoryQid": "Q2811",
        "modelQid": "Q1428357",
        "limit": 180,
    },
    {
        "id": "aircraft-carriers",
        "label": "Aircraft Carriers",
        "group": "Sea",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q17205",
        "sourceType": "wikidata",
        "categoryQid": "Q17205",
        "modelQid": "Q559026",
        "descriptionContainsAny": ("aircraft carrier",),
        "limit": 120,
    },
    {
        "id": "spacecraft",
        "label": "Spacecraft",
        "group": "Space",
        "sourceLabel": "Wikidata",
        "sourceUrl": "https://www.wikidata.org/wiki/Q40218",
        "sourceType": "wikidata",
        "categoryQid": "Q40218",
        "modelQid": "Q117384805",
        "limit": 180,
    },
]


def fetch_category_items(category: dict) -> list[dict]:
    if category["sourceType"] == "wikidata":
        return wikidata_family_items(
            category_qid=category["categoryQid"],
            model_qid=category["modelQid"],
            limit=category["limit"],
            label_contains_any=tuple(category.get("labelContainsAny", ())),
            description_contains_any=tuple(
                category.get("descriptionContainsAny", ())
            ),
        )

    if category["sourceType"] == "category":
        return category_names(
            category_titles=category["categoryTitles"],
            skip_exact=category.get("skipExact", set()),
            skip_if_contains=tuple(category.get("skipContains", ())),
            limit=category["limit"],
        )

    return table_names(
        page=category["page"],
        table_indices=category.get("tableIndices", "all"),
        name_parts=category["nameParts"],
        skip_exact=category.get("skipExact", set()),
        skip_if_contains=tuple(category.get("skipContains", ())),
        limit=category["limit"],
    )


def merge_items(categories: list[dict]) -> dict:
    vehicles: dict[str, dict] = {}
    category_counts = defaultdict(int)

    for category in categories:
        items = fetch_category_items(category)
        category["_rawCount"] = len(items)

        for item in items:
            name = item["name"]
            key = name.casefold()

            if key not in vehicles:
                vehicles[key] = {
                    "name": name,
                    "description": item.get("description", ""),
                    "wikiTitle": item.get("wikiTitle", ""),
                    "categories": [],
                    "groups": [],
                    "sourceLabels": [],
                    "sourceUrls": [],
                }

            record = vehicles[key]
            if not record["description"] and item.get("description"):
                record["description"] = item["description"]
            if not record.get("wikiTitle") and item.get("wikiTitle"):
                record["wikiTitle"] = item["wikiTitle"]

            if category["id"] not in record["categories"]:
                record["categories"].append(category["id"])
                category_counts[category["id"]] += 1

            if category["group"] not in record["groups"]:
                record["groups"].append(category["group"])

            if category["sourceLabel"] not in record["sourceLabels"]:
                record["sourceLabels"].append(category["sourceLabel"])

            if category["sourceUrl"] not in record["sourceUrls"]:
                record["sourceUrls"].append(category["sourceUrl"])

    ordered_vehicles = sorted(
        vehicles.values(),
        key=lambda item: (item["groups"][0], item["name"].casefold()),
    )
    fetch_page_images(ordered_vehicles)
    fetch_vehicle_years(ordered_vehicles)
    era_records = build_era_records(ordered_vehicles)

    for vehicle in ordered_vehicles:
        vehicle.pop("wikidataId", None)

    category_records = []
    for category in categories:
        category_records.append(
            {
                "id": category["id"],
                "label": category["label"],
                "group": category["group"],
                "count": category_counts[category["id"]],
                "sourceLabel": category["sourceLabel"],
                "sourceUrl": category["sourceUrl"],
            }
        )

    source_records = []
    seen_sources = set()
    for category in categories:
        key = (category["sourceLabel"], category["sourceUrl"])
        if key in seen_sources:
            continue
        seen_sources.add(key)
        source_records.append(
            {
                "label": category["sourceLabel"],
                "url": category["sourceUrl"],
            }
        )

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "vehicleCount": len(ordered_vehicles),
            "categoryCount": len(category_records),
            "datedVehicleCount": sum(1 for vehicle in ordered_vehicles if vehicle.get("year")),
            "eraCount": len(era_records),
            "imageCount": sum(1 for vehicle in ordered_vehicles if vehicle.get("image")),
        },
        "licenses": [
            {
                "label": "Wikidata structured data (CC0)",
                "url": "https://www.wikidata.org/wiki/Wikidata:Main_Page",
            },
            {
                "label": "Wikipedia list pages (CC BY-SA)",
                "url": "https://en.wikipedia.org/wiki/Wikipedia:Copyrights",
            },
        ],
        "sources": source_records,
        "categories": category_records,
        "eras": era_records,
        "vehicles": ordered_vehicles,
    }


def main() -> None:
    dataset = merge_items(CATEGORIES)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    json_path = DATA_DIR / "vehicles.json"
    js_path = DATA_DIR / "vehicles.js"

    json_text = json.dumps(dataset, indent=2, ensure_ascii=False)
    json_path.write_text(json_text + "\n", encoding="utf-8")
    js_path.write_text(
        "window.VEHICLE_DATA = " + json.dumps(dataset, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print(
        f"Built dataset with {dataset['summary']['vehicleCount']} vehicles "
        f"across {dataset['summary']['categoryCount']} categories."
    )


if __name__ == "__main__":
    main()
