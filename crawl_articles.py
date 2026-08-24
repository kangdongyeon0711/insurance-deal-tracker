#!/usr/bin/env python3
"""RSS 피드에서 보험사 부동산/인프라 투자 관련 기사를 찾아 이메일로 알려준다."""

import argparse
import json
import os
import pathlib
import re
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText

import feedparser

from infer_deal_structure import infer_deal_structure

# ── 설정 ──────────────────────────────────────────────────────────────────
# RSS 피드 목록. 이 개발 환경은 네트워크 egress가 막혀 있어 아래 URL을 직접
# 검증하지 못했습니다. 로컬에서 실행하기 전에 각 피드가 실제로 살아있는지,
# 그리고 원하는 언론사가 포함됐는지 꼭 확인하고 필요에 따라 추가/교체하세요.
RSS_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("한국경제 경제", "https://www.hankyung.com/feed/economy"),
    ("매일경제 경제", "https://www.mk.co.kr/rss/30000001/"),
]

# 두 그룹 모두에서 최소 1개 키워드가 제목+요약에 있어야 Claude 호출 대상 후보가 됨.
# 보험사 실제 상호(현대해상, 신한라이프 등)는 "보험"/"생명" 같은 일반 패턴에
# 안 걸리는 경우가 있어 "해상", "라이프"처럼 상호에 쓰이는 조각도 포함해야 함.
INSURER_KEYWORDS = ["보험", "생명", "화재", "손보", "해상", "라이프", "공제회"]
DEAL_KEYWORDS = ["부동산", "인프라", "지분", "매입", "인수", "대출", "투자", "매각"]

STATE_PATH = pathlib.Path("state/crawl_seen.json")

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").strip()


def load_seen() -> set[str]:
    if STATE_PATH.exists():
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def matches_keywords(text: str) -> bool:
    has_insurer = any(k in text for k in INSURER_KEYWORDS)
    has_deal = any(k in text for k in DEAL_KEYWORDS)
    return has_insurer and has_deal


def fetch_candidates(seen: set[str]) -> list[dict]:
    """RSS 피드를 모두 읽어, 아직 못 본 링크 중 키워드 조건을 만족하는 후보만 반환."""
    candidates = []
    for feed_name, feed_url in RSS_FEEDS:
        parsed = feedparser.parse(feed_url)
        if parsed.bozo:
            print(
                f"[경고] {feed_name} 피드를 읽는 중 문제 발생: {parsed.bozo_exception}",
                file=sys.stderr,
            )
        for entry in parsed.entries:
            link = entry.get("link")
            if not link or link in seen:
                continue
            title = _strip_html(entry.get("title", ""))
            summary = _strip_html(entry.get("summary", ""))
            if not matches_keywords(f"{title} {summary}"):
                continue
            candidates.append(
                {
                    "source": feed_name,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": entry.get("published", ""),
                }
            )
    return candidates


def _format_hit(hit: dict) -> str:
    result = hit["result"]
    investor = result["investor"]["name"]
    assets = ", ".join(
        a.get("asset_name") or a.get("sub_type") or "자산 미상"
        for a in result["target_asset"]["assets"]
    )
    status = result["deal_status"]["current_state"]
    confidence = result["confidence"]["overall"]
    return (
        f"■ {hit['title']}\n"
        f"  출처: {hit['source']} | {hit['link']}\n"
        f"  투자자: {investor}\n"
        f"  자산: {assets}\n"
        f"  상태: {status} | 판단 확신도: {confidence}\n"
        f"  비고: {result['confidence']['notes']}\n"
    )


def send_email(hits: list[dict]) -> None:
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ.get("EMAIL_FROM", smtp_user)
    email_to = os.environ["EMAIL_TO"]

    body = "\n".join(_format_hit(hit) for hit in hits)

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = (
        f"[보험사 부동산/인프라 투자 알림] {len(hits)}건 발견 "
        f"({datetime.now().strftime('%Y-%m-%d')})"
    )
    msg["From"] = email_from
    msg["To"] = email_to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, [email_to], msg.as_string())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RSS 피드에서 보험사 부동산/인프라 투자 기사를 찾아 이메일로 알려줍니다."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Claude API 호출과 이메일 전송 없이 키워드로 걸러진 후보만 출력합니다",
    )
    args = parser.parse_args()

    seen = load_seen()
    candidates = fetch_candidates(seen)

    if args.dry_run:
        print(f"[dry-run] 키워드로 걸러진 후보 {len(candidates)}건:")
        for c in candidates:
            print(f"- [{c['source']}] {c['title']} ({c['link']})")
        return

    hits = []
    for c in candidates:
        text = f"{c['title']}\n\n{c['summary']}"
        try:
            result = infer_deal_structure(text)
        except Exception as e:
            print(f"[오류] '{c['title']}' 추론 실패: {e}", file=sys.stderr)
            continue
        seen.add(c["link"])
        hits.append({**c, "result": result})

    save_seen(seen)

    if hits:
        send_email(hits)
        print(f"{len(hits)}건 발견, 이메일 전송 완료.")
    else:
        print("새로 발견된 딜이 없습니다.")


if __name__ == "__main__":
    main()
