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

다음은 참고할 few-shot 예시입니다.

예시 1)
기사 요지: 신창재 교보생명 회장이 재무적투자자(FI) 지분을 인수하기 위해
신한투자증권·한국투자증권이 설립한 SPC를 활용, 본인 보유 교보생명 지분을
담보로 주식담보대출을 실행하여 약 4천억 원을 조달함.

출력:
{
  "investor": {
    "name": "신창재 회장 (교보생명)",
    "type": "SPC/PFV",
    "is_direct": false
  },
  "target_asset": {
    "category": "부동산",
    "sub_type": null,
    "location": null,
    "asset_name": null
  },
  "deal_structure": {
    "instrument": "지분투자",
    "vehicle": "SPC",
    "ownership_pct": 9.83,
    "loan_amount": 4000,
    "ltv_pct": null,
    "tranche_position": null
  },
  "return_structure": {
    "type": "혼합",
    "expected_return_pct": null,
    "maturity": null
  },
  "confidence": {
    "overall": "medium",
    "notes": "이 건은 부동산/인프라 자산 투자가 아니라 지분 인수 자금조달 사례. 담보 자산은 교보생명 주식이며 대출 재원 조달 목적의 SPC 구조. 실제 부동산/인프라 딜과는 성격이 다르므로 스키마 적용 시 category를 '해당없음'으로 처리하거나 필터링 필요."
  },
  "source_evidence": "SPC를 통해 사들인 지분은 교보생명 지분을 담보로 한 대출로 조달되었다고 보도됨."
}

이 예시는 스키마가 "부동산/인프라가 아닌 딜"을 만났을 때 confidence.notes로
어떻게 걸러내는지 보여줍니다.

예시 2)
기사 요지: 현대해상·NH농협생명·한화손보·지방행정공제회·KB손보 등 국내 보험사·공제회가
영국 M25 고속도로 운영사(코넥트플러스) 지분 20%를 약 2800억원에 공동 인수함.
하나금융투자·한화투자증권이 총액인수 후 셀다운, 미래에셋자산운용·한화자산운용이
재간접펀드를 운용. 잔여 계약기간 22년 동안 연 6%대 수익률 기대.

출력:
{
  "investor": {
    "name": "현대해상·NH농협생명·한화손보·한화생명·지방행정공제회·KB손보·흥국화재 등 보험사·공제회 컨소시엄",
    "type": "보험사",
    "is_direct": false
  },
  "target_asset": {
    "category": "인프라",
    "sub_type": "도로",
    "location": "해외, 영국 런던",
    "asset_name": "M25 고속도로 (사업시행사 코넥트플러스)"
  },
  "deal_structure": {
    "instrument": "지분투자",
    "vehicle": "펀드",
    "ownership_pct": 20,
    "loan_amount": null,
    "ltv_pct": null,
    "tranche_position": null
  },
  "return_structure": {
    "type": "배당형",
    "expected_return_pct": 6,
    "maturity": "22년 (2039년까지 운영)"
  },
  "confidence": {
    "overall": "medium",
    "notes": "하나금융투자·한화투자증권이 총액인수 후 셀다운, 미래에셋자산운용·한화자산운용이 '재간접펀드'를 운용한다고 명시되어 vehicle을 '펀드'로 판단. 다만 각 보험사가 '투자심의위원회'를 열어 개별 승인했다는 표현도 있어, 최종 보유 구조가 순수 재간접펀드 지분인지 개별 SPC 지분인지는 기사만으로 완전히 확정하기 어려움. RBC 위험계수 인하 혜택(위험계수 6% 또는 0%) 언급은 있으나 이는 규제상 인센티브 설명이지 딜 구조 자체를 바꾸지는 않음."
  },
  "source_evidence": "한국 기관들이 코넥트플러스 지분 20%를 에쿼틱스·달모어캐피털과 공동투자로 인수하며, 총액인수·셀다운은 하나금융투자·한화투자증권이, 재간접펀드 운용은 미래에셋자산운용·한화자산운용이 맡았다고 보도됨. 잔여 계약기간 22년 동안 연 6%대 수익률을 기대한다고 명시됨."
}

이 예시는 "진짜 인프라 지분투자" 케이스이며, vehicle이 펀드/SPC 중 무엇인지
기사만으로 완전히 단정할 수 없어 confidence가 medium으로 나온 전형적인
사례입니다. 딜 주선사(총액인수·셀다운)와 자산운용사(재간접펀드 운용)의
역할이 분리되어 있을 때 vehicle 판단이 어떻게 이뤄지는지 보여줍니다.
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
