#!/usr/bin/env python3
"""보험사 부동산·인프라 투자 기사를 입력받아 딜 구조를 추론하고 JSON으로 출력한다."""

import argparse
import json
import pathlib
import sys

import anthropic

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
당신은 국내/해외 보험사의 부동산 및 인프라 투자 기사를 읽고,
계약 구조와 수익 구조를 추론하는 애널리스트입니다.

규칙:
1. 기사에 명시된 사실과 당신이 추론한 내용을 반드시 구분하세요.
   추론한 항목은 confidence.notes에 그 근거와 불확실성을 밝히세요.
2. 기사에 없는 숫자(LTV, 수익률 등)를 지어내지 마세요. 모르면 null로 두세요.
3. "SPC를 통한 간접투자"인지 "보험사 직접 투자"인지는
   투자주체 표기(예: OO생명, OO자산운용, OO SPC)를 근거로 판단하세요.
4. 딜 구조가 지분인지 대출인지 모호하면, 기사에 나온 표현(예: "인수", "출자", "대출", "매입")을
   근거 문장과 함께 confidence를 medium 또는 low로 표기하세요.
5. 반드시 지정된 JSON 스키마 형식으로만 응답하세요. 다른 설명 텍스트를 추가하지 마세요.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "investor": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["보험사", "자산운용사", "SPC/PFV", "기타"],
                },
                "is_direct": {
                    "type": "boolean",
                    "description": "보험사가 직접 투자하는지, SPC/펀드를 통한 간접투자인지",
                },
            },
            "required": ["name", "type", "is_direct"],
            "additionalProperties": False,
        },
        "target_asset": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["부동산", "인프라"]},
                "sub_type": {
                    "type": ["string", "null"],
                    "description": "예: 오피스, 물류센터, 데이터센터, 발전소, 도로 등",
                },
                "location": {
                    "type": ["string", "null"],
                    "description": "국내/해외, 도시명",
                },
                "asset_name": {"type": ["string", "null"]},
            },
            "required": ["category", "sub_type", "location", "asset_name"],
            "additionalProperties": False,
        },
        "deal_structure": {
            "type": "object",
            "properties": {
                "instrument": {
                    "type": "string",
                    "enum": ["지분투자", "선순위대출", "후순위/메자닌대출", "채권", "혼합"],
                },
                "vehicle": {
                    "type": "string",
                    "enum": ["직접보유", "SPC", "PFV", "리츠", "펀드"],
                },
                "ownership_pct": {"type": ["number", "null"]},
                "loan_amount": {
                    "type": ["number", "null"],
                    "description": "단위: 억원",
                },
                "ltv_pct": {"type": ["number", "null"]},
                "tranche_position": {
                    "type": ["string", "null"],
                    "enum": ["선순위", "중순위", "후순위", None],
                },
            },
            "required": [
                "instrument",
                "vehicle",
                "ownership_pct",
                "loan_amount",
                "ltv_pct",
                "tranche_position",
            ],
            "additionalProperties": False,
        },
        "return_structure": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["임대수익형", "이자수익형", "캐피탈게인형", "배당형", "혼합"],
                },
                "expected_return_pct": {"type": ["number", "null"]},
                "maturity": {
                    "type": ["string", "null"],
                    "description": "예: 5년, 2031년 만기",
                },
            },
            "required": ["type", "expected_return_pct", "maturity"],
            "additionalProperties": False,
        },
        "confidence": {
            "type": "object",
            "properties": {
                "overall": {"type": "string", "enum": ["high", "medium", "low"]},
                "notes": {
                    "type": "string",
                    "description": "기사에 명시되지 않아 추론한 부분을 서술",
                },
            },
            "required": ["overall", "notes"],
            "additionalProperties": False,
        },
        "source_evidence": {
            "type": "string",
            "description": "기사에서 이 구조를 판단한 근거 문장 1~2개 (요약, 직접 인용 금지)",
        },
    },
    "required": [
        "investor",
        "target_asset",
        "deal_structure",
        "return_structure",
        "confidence",
        "source_evidence",
    ],
    "additionalProperties": False,
}


def infer_deal_structure(article_text: str) -> dict:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": article_text}],
        output_config={
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}
        },
    )

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="기사 텍스트를 입력받아 보험사 부동산/인프라 투자 딜 구조를 JSON으로 추론합니다."
    )
    parser.add_argument(
        "article_text", nargs="?", help="분석할 기사 본문 텍스트 (--file과 함께 사용 불가)"
    )
    parser.add_argument(
        "-f", "--file", help="기사 본문이 담긴 텍스트 파일 경로 (article_text 인자 대신 사용)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API를 호출하지 않고 전송될 system 프롬프트, 모델, 기사 텍스트만 출력합니다",
    )
    args = parser.parse_args()

    if bool(args.article_text) == bool(args.file):
        parser.error("article_text 인자와 --file 중 정확히 하나를 지정하세요.")

    if args.file:
        try:
            article_text = pathlib.Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"파일을 읽을 수 없습니다: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        article_text = args.article_text

    if args.dry_run:
        print(f"[dry-run] model: {MODEL}")
        print(f"[dry-run] system prompt:\n{SYSTEM_PROMPT}")
        print(f"[dry-run] article_text ({len(article_text)}자):\n{article_text}")
        return

    try:
        result = infer_deal_structure(article_text)
    except anthropic.BadRequestError as e:
        print(f"잘못된 요청: {e.message}", file=sys.stderr)
        sys.exit(1)
    except anthropic.AuthenticationError:
        print("API 키가 유효하지 않습니다.", file=sys.stderr)
        sys.exit(1)
    except anthropic.PermissionDeniedError:
        print("API 키에 필요한 권한이 없습니다.", file=sys.stderr)
        sys.exit(1)
    except anthropic.NotFoundError:
        print("모델 또는 엔드포인트를 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "60")
        print(f"요청 한도 초과. {retry_after}초 후 재시도하세요.", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIConnectionError:
        print("네트워크 오류가 발생했습니다.", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIStatusError as e:
        print(f"API 오류 ({e.status_code}): {e.message}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
