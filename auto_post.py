#!/usr/bin/env python3
"""Livedoor Blog AtomPub 投稿スクリプト（GitHub Actions / ローカル両用）。

必要な環境変数:
  LIVEDOOR_ID, ATOMPUB_PASSWORD, BLOG_ID

任意:
  SITE_ORIGIN   既定 https://www.sunverdir.com
  ARTICLE_TITLE / ARTICLE_BODY / ARTICLE_CATEGORY
  PUBLISH=true  のときだけ公開。未設定なら下書き。
  DRY_RUN=true  XML を標準出力して終了（API を叩かない）
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests

ENDPOINT_TMPL = "https://livedoor.blogcms.jp/atompub/{blog_id}/article"
SITE_ORIGIN_DEFAULT = "https://www.sunverdir.com"
JSONLD_START = "<!-- sunverdir-seo:jsonld -->"
JSONLD_END = "<!-- /sunverdir-seo:jsonld -->"
JSONLD_BLOCK_RE = re.compile(
    re.escape(JSONLD_START) + r".*?" + re.escape(JSONLD_END),
    re.DOTALL,
)
ARTICLE_ID_RE = re.compile(r"article-[^.]+\.(\d+)")

# supreme-json-ld と同期した人物スキーマ（ProfilePage.mainEntity）
PERSON_ENTITY = {
    "@type": "Person",
    "@id": "https://www.sunverdir.com/profile#person",
    "name": "菅野敦也",
    "familyName": "菅野",
    "givenName": "敦也",
    "alternateName": [
        "すがのあつなり",
        "スガノアツナリ",
        "Atsunari Sugano",
        "Sugano Atsunari",
    ],
    "birthDate": "1962-06-04",
    "gender": "https://schema.org/Male",
    "url": "https://www.sunverdir.com/profile",
    "image": "https://upload.wikimedia.org/wikipedia/commons/d/d5/Atsunari_Sugano.jpg",
    "description": (
        "岡山を拠点に地方創生AXやSociety5.0を推進する社会起業家・政策起業家・発明家。"
        "経営DXラボCIO 兼 SME、NPO法人超教育ラボラトリー代表理事 兼 Society5.0事業部長。"
    ),
    "jobTitle": [
        "社会起業家",
        "政策起業家",
        "発明家",
        "著作家",
        "研究者",
        "経営DXラボCIO",
        "中小企業アドバイザー",
    ],
    "worksFor": [
        {"@type": "Organization", "name": "経営DXラボ", "url": "https://www.maemuki.info/"},
        {
            "@type": "Organization",
            "name": "NPO法人超教育ラボラトリー",
            "url": "https://www.city-okayama.net/",
        },
    ],
    "hasCredential": [
        {
            "@type": "EducationalOccupationalCredential",
            "name": "G検定",
            "recognizedBy": {
                "@type": "Organization",
                "name": "一般社団法人日本ディープラーニング協会",
            },
        },
        {
            "@type": "EducationalOccupationalCredential",
            "name": "GX検定 アドバンスト",
            "recognizedBy": {"@type": "Organization", "name": "株式会社スキルアップNeXt"},
        },
        {
            "@type": "EducationalOccupationalCredential",
            "name": "中小企業アドバイザー（高度化事業）",
            "recognizedBy": {
                "@type": "Organization",
                "name": "独立行政法人中小企業基盤整備機構",
            },
        },
    ],
    "alumniOf": {
        "@type": "CollegeOrUniversity",
        "name": "慶應義塾大学",
        "sameAs": "https://ja.wikipedia.org/wiki/慶應義塾大学",
    },
    "knowsAbout": [
        {"@type": "Thing", "name": "Society 5.0", "sameAs": "https://ja.wikipedia.org/wiki/Society_5.0"},
        {"@type": "Thing", "name": "地方創生", "sameAs": "https://ja.wikipedia.org/wiki/地方創生"},
        {
            "@type": "Thing",
            "name": "AX (AI Transformation)",
            "sameAs": "https://ja.wikipedia.org/wiki/AX_(曖昧さ回避)",
        },
        {
            "@type": "Thing",
            "name": "GX (Green Transformation)",
            "sameAs": "https://ja.wikipedia.org/wiki/グリーントランスフォーメーション",
        },
        {"@type": "Thing", "name": "web3", "sameAs": "https://ja.wikipedia.org/wiki/Web3"},
    ],
    "homeLocation": {"@type": "Place", "name": "岡山県岡山市"},
    "sameAs": [
        "https://www.wikidata.org/wiki/Q100455577",
        "https://x.com/SunVerdir",
        "https://www.linkedin.com/in/sunverdir",
        "https://www.facebook.com/SunVerdir",
        "https://orcid.org/0009-0003-1371-5267",
        "https://github.com/SunVerdir",
    ],
}


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def require_secrets() -> tuple[str, str, str]:
    livedoor_id = os.environ.get("LIVEDOOR_ID", "").strip()
    password = os.environ.get("ATOMPUB_PASSWORD", "").strip()
    blog_id = os.environ.get("BLOG_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("LIVEDOOR_ID", livedoor_id),
            ("ATOMPUB_PASSWORD", password),
            ("BLOG_ID", blog_id),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Secrets が未設定です: " + ", ".join(missing)
        )
    return livedoor_id, password, blog_id


def generate_wsse_header(username: str, password: str) -> str:
    nonce = os.urandom(16)
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = hashlib.sha1(nonce + created.encode("utf-8") + password.encode("utf-8")).digest()
    return (
        f'UsernameToken Username="{username}", '
        f'PasswordDigest="{base64.b64encode(digest).decode("ascii")}", '
        f'Nonce="{base64.b64encode(nonce).decode("ascii")}", '
        f'Created="{created}"'
    )


def build_jsonld(title: str, body_html: str, page_url: str | None = None) -> dict:
    site = os.environ.get("SITE_ORIGIN", SITE_ORIGIN_DEFAULT).rstrip("/")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    plain = re.sub(r"<[^>]+>", "", body_html)
    summary = re.sub(r"\s+", " ", plain).strip()[:180] or title
    url = page_url or f"{site}/"
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": title,
                "description": summary,
                "inLanguage": "ja",
                "datePublished": now,
                "dateModified": now,
                "url": url,
                "mainEntityOfPage": url,
                "author": {"@id": PERSON_ENTITY["@id"]},
                "publisher": {
                    "@type": "Organization",
                    "name": "経営DXラボ",
                    "url": "https://www.maemuki.info/",
                },
                "isPartOf": {"@type": "Blog", "name": "政策形成ブログ", "url": site},
                "about": PERSON_ENTITY.get("knowsAbout", []),
            },
            PERSON_ENTITY,
        ],
    }


def render_jsonld_block(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe = serialized.replace("</", "<\\/")
    return (
        f"{JSONLD_START}"
        f'<script type="application/ld+json">{safe}</script>'
        f"{JSONLD_END}"
    )


def inject_jsonld(body_html: str, title: str, page_url: str | None = None) -> str:
    block = render_jsonld_block(build_jsonld(title, body_html, page_url))
    if JSONLD_BLOCK_RE.search(body_html):
        return JSONLD_BLOCK_RE.sub(block, body_html, count=1)
    # 旧コメント形式があれば一度だけ置換
    legacy = re.compile(
        r"<!-- SEO JSON-LD Auto-Injected -->\s*<script type=\"application/ld\+json\">.*?</script>",
        re.DOTALL,
    )
    if legacy.search(body_html):
        return legacy.sub(block, body_html, count=1)
    return body_html.rstrip() + "\n\n" + block + "\n"


def escape_cdata(text: str) -> str:
    return text.replace("]]>", "]]]]><![CDATA[>")


def build_entry_xml(
    title: str,
    body_html: str,
    category: str | None,
    is_draft: bool,
) -> bytes:
    content = escape_cdata(inject_jsonld(body_html, title))
    category_xml = (
        f'<category term="{html.escape(category, quote=True)}" />' if category else ""
    )
    draft_val = "yes" if is_draft else "no"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">
  <title>{html.escape(title)}</title>
  {category_xml}
  <app:control><app:draft>{draft_val}</app:draft></app:control>
  <content type="html"><![CDATA[{content}]]></content>
</entry>
"""
    return xml.encode("utf-8")


def parse_article_id(xml_text: str) -> str | None:
    match = ARTICLE_ID_RE.search(xml_text)
    return match.group(1) if match else None


def atom_headers(username: str, password: str) -> dict[str, str]:
    return {
        "Authorization": 'WSSE profile="UsernameToken"',
        "X-WSSE": generate_wsse_header(username, password),
        "Content-Type": "application/atom+xml;type=entry",
        "User-Agent": "policy-seo-automation/2.0",
    }


def post_article(
    title: str,
    body_html: str,
    category: str | None = None,
    is_draft: bool = True,
    *,
    dry_run: bool = False,
    timeout: float = 30.0,
) -> str | None:
    xml_payload = build_entry_xml(title, body_html, category, is_draft)
    if dry_run:
        sys.stdout.write(xml_payload.decode("utf-8"))
        return None

    livedoor_id, password, blog_id = require_secrets()
    url = ENDPOINT_TMPL.format(blog_id=blog_id)
    response = requests.post(
        url,
        data=xml_payload,
        headers=atom_headers(livedoor_id, password),
        timeout=timeout,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"投稿失敗 [{response.status_code}]: {response.text[:2000]}"
        )
    article_id = parse_article_id(response.text)
    location = response.headers.get("Location", "")
    print(
        json.dumps(
            {
                "ok": True,
                "status": response.status_code,
                "article_id": article_id,
                "location": location,
                "draft": is_draft,
                "title": title,
            },
            ensure_ascii=False,
        )
    )
    return article_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Livedoor AtomPub で記事を投稿する")
    parser.add_argument("--title", default=os.environ.get("ARTICLE_TITLE", ""))
    parser.add_argument("--body", default=os.environ.get("ARTICLE_BODY", ""))
    parser.add_argument("--body-file", default=os.environ.get("ARTICLE_BODY_FILE", ""))
    parser.add_argument("--category", default=os.environ.get("ARTICLE_CATEGORY", "Society 5.0"))
    parser.add_argument("--publish", action="store_true", help="公開する（既定は下書き）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    title = args.title.strip()
    body = args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    body = body.strip()
    is_draft = not (args.publish or env_truthy("PUBLISH"))
    dry_run = args.dry_run or env_truthy("DRY_RUN")

    if not title or not body:
        print(
            "投稿する本文がありません。"
            "ARTICLE_TITLE と ARTICLE_BODY（または --title / --body）を設定してください。"
            "週次 Actions で同じサンプルを公開し続けないための安全装置です。",
            file=sys.stderr,
        )
        return 0

    post_article(
        title=title,
        body_html=body,
        category=args.category or None,
        is_draft=is_draft,
        dry_run=dry_run,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
