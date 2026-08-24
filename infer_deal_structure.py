#!/usr/bin/env python3
"""보험사 부동산·인프라 투자 기사를 입력받아 딜 구조를 추론하고 JSON으로 출력한다."""

import argparse
import html
import json
import pathlib
import sys

import anthropic

MODEL = "claude-sonnet-4-6"

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
5. 반드시 위 JSON 스키마 형식으로만 응답하세요. 다른 설명 텍스트를 추가하지 마세요.
6. 참여 기관 유형이 보험사·공제회·증권사·신협 등으로 혼합되어 있으면,
   investor.type은 앵커(최대) 투자자 기준으로 정하고, 나머지 기관 구성은
   investor.name에 병기하세요. confidence.notes에도 컨소시엄 구성이 혼합임을 밝히세요.
7. "선순위/후순위로 구분 투자"라는 표현이 지분 내 우선순위 구조(우선주 등)를
   의미하는지, 대출 트랜치를 의미하는지 기사만으로 불명확하면 instrument를 "혼합"으로
   표기하세요. 이때 tranche_position은 전체 딜 구조상 존재하는 트랜치 종류만 기술하고,
   특정 투자자(예: 앵커 투자자)가 그중 어디에 속하는지는 기사에 명시되지 않은 한 null로 두세요.
8. 하나의 딜에서 여러 자산(다른 도시·다른 건물 등)을 한 번에 매입하는 "패키지 딜"인 경우,
   target_asset.assets 배열에 자산별로 별도 원소를 만들어 나열하고,
   각 원소의 tenants에는 해당 자산에 대응하는 임차인만 기재하세요.
   confidence.notes에 "패키지 딜"임을 명시하세요.
9. 기사에 나온 다른 숫자들로 계산 가능한 값(예: 대출액 ÷ 총투자액 = LTV)이라도,
   기사 원문에 해당 용어(LTV 등)가 직접 쓰이지 않았다면 해당 필드는 null로 두고,
   confidence.notes에 "계산상 추정 가능하나 원문에 명시되지 않음"이라고 밝히세요.
   임의로 계산한 값을 필드에 채워 넣지 마세요.
10. 한 기사가 서로 다른 여러 투자 건(예: 사모펀드 운용사 지분 인수 + 부동산 지분 인수)을
    함께 다루는 경우, 이 스키마(부동산/인프라 자산 투자)에 해당하는 딜만 추출하세요.
    스키마 범위 밖의 다른 딜은 confidence.notes에 "기사에 다른 딜(내용 요약)도
    언급되나 스키마 범위 밖이라 제외함"이라고 밝히세요.
11. ownership_pct는 항상 "이번 거래로 취득한 지분율"을 의미합니다. 기존에 보유하고
    있던 지분과 이번 거래분을 합산한 최종 보유 지분율이 기사에 함께 언급되면,
    ownership_pct에는 이번 거래분만 기재하고 최종 보유율은 confidence.notes에
    별도로 명시하세요.
12. 기사가 딜의 최초 설계가 아니라 딜 이후의 상태 변화(연체, 채무불이행, 손실,
    채권 매각, 만기 도과 등)를 다루는 경우, deal_status 필드를 반드시 채우세요.
    이때 deal_structure와 return_structure는 원 딜 조건(대출 원금, 만기 등
    기사에 나온 만큼)을 그대로 기재하고, 상태 변화 관련 서술(왜 손실이
    발생했는지, 현재 어떤 절차가 진행 중인지)은 deal_status.event_summary에
    담으세요. 딜의 최초 설계만 다루는 일반적인 기사는 deal_status.current_state를
    "정상"으로 두고 event_summary는 null로 두세요.
"""

# "## 3. Few-shot 예시" 섹션 — 각 예시를 실제 user/assistant 대화 턴으로 만들어
# messages에 포함시킨다 (SYSTEM_PROMPT에는 텍스트로 넣지 않음).
FEW_SHOT_EXAMPLES = [
    {
        "article": (
            "기사 요지: 신창재 교보생명 회장이 재무적투자자(FI) 지분을 인수하기 위해\n"
            "신한투자증권·한국투자증권이 설립한 SPC를 활용, 본인 보유 교보생명 지분을\n"
            "담보로 주식담보대출을 실행하여 약 4천억 원을 조달함."
        ),
        "output": {
            "investor": {
                "name": "신창재 회장 (교보생명)",
                "type": "SPC/PFV",
                "is_direct": False,
            },
            "target_asset": {
                "category": "부동산",
                "assets": [
                    {
                        "sub_type": None,
                        "location": None,
                        "asset_name": None,
                        "tenants": None,
                    }
                ],
            },
            "deal_structure": {
                "instrument": "지분투자",
                "vehicle": "SPC",
                "ownership_pct": 9.83,
                "loan_amount": 4000,
                "ltv_pct": None,
                "tranche_position": None,
            },
            "return_structure": {
                "type": "혼합",
                "expected_return_pct": None,
                "maturity": None,
            },
            "deal_status": {
                "current_state": "정상",
                "event_summary": None,
                "realized_loss": None,
            },
            "confidence": {
                "overall": "medium",
                "notes": (
                    "이 건은 부동산/인프라 자산 투자가 아니라 지분 인수 자금조달 사례. "
                    "담보 자산은 교보생명 주식이며 대출 재원 조달 목적의 SPC 구조. "
                    "실제 부동산/인프라 딜과는 성격이 다르므로 스키마 적용 시 category를 "
                    "'해당없음'으로 처리하거나 필터링 필요."
                ),
            },
            "source_evidence": "SPC를 통해 사들인 지분은 교보생명 지분을 담보로 한 대출로 조달되었다고 보도됨.",
        },
    },
    {
        "article": (
            "기사 요지: 현대해상·NH농협생명·한화손보·지방행정공제회·KB손보 등 국내 보험사·공제회가\n"
            "영국 M25 고속도로 운영사(코넥트플러스) 지분 20%를 약 2800억원에 공동 인수함.\n"
            "하나금융투자·한화투자증권이 총액인수 후 셀다운, 미래에셋자산운용·한화자산운용이\n"
            "재간접펀드를 운용. 잔여 계약기간 22년 동안 연 6%대 수익률 기대."
        ),
        "output": {
            "investor": {
                "name": (
                    "현대해상·NH농협생명·한화손보·한화생명·지방행정공제회·"
                    "KB손보·흥국화재 등 보험사·공제회 컨소시엄"
                ),
                "type": "보험사",
                "is_direct": False,
            },
            "target_asset": {
                "category": "인프라",
                "assets": [
                    {
                        "sub_type": "도로",
                        "location": "해외, 영국 런던",
                        "asset_name": "M25 고속도로 (사업시행사 코넥트플러스)",
                        "tenants": None,
                    }
                ],
            },
            "deal_structure": {
                "instrument": "지분투자",
                "vehicle": "펀드",
                "ownership_pct": 20,
                "loan_amount": None,
                "ltv_pct": None,
                "tranche_position": None,
            },
            "return_structure": {
                "type": "배당형",
                "expected_return_pct": 6,
                "maturity": "22년 (2039년까지 운영)",
            },
            "deal_status": {
                "current_state": "정상",
                "event_summary": None,
                "realized_loss": None,
            },
            "confidence": {
                "overall": "medium",
                "notes": (
                    "하나금융투자·한화투자증권이 총액인수 후 셀다운, 미래에셋자산운용·한화자산운용이 "
                    "'재간접펀드'를 운용한다고 명시되어 vehicle을 '펀드'로 판단. 다만 각 보험사가 "
                    "'투자심의위원회'를 열어 개별 승인했다는 표현도 있어, 최종 보유 구조가 순수 "
                    "재간접펀드 지분인지 개별 SPC 지분인지는 기사만으로 완전히 확정하기 어려움. "
                    "RBC 위험계수 인하 혜택(위험계수 6% 또는 0%) 언급은 있으나 이는 규제상 인센티브 "
                    "설명이지 딜 구조 자체를 바꾸지는 않음."
                ),
            },
            "source_evidence": (
                "한국 기관들이 코넥트플러스 지분 20%를 에쿼틱스·달모어캐피털과 공동투자로 인수하며, "
                "총액인수·셀다운은 하나금융투자·한화투자증권이, 재간접펀드 운용은 미래에셋자산운용·"
                "한화자산운용이 맡았다고 보도됨. 잔여 계약기간 22년 동안 연 6%대 수익률을 기대한다고 명시됨."
            ),
        },
    },
    {
        "article": (
            "기사 요지: 한화생명을 앵커 투자자로 교보생명·NH생명·신협·삼성증권·HMC투자증권 등\n"
            "기관투자가들이 이지스자산운용을 통해 파리·워싱턴·몬트리올 소재 오피스 빌딩 3곳을\n"
            "약 1조원(패키지)에 매입. 5000억원은 국내 기관이 선순위·후순위로 구분 투자,\n"
            "나머지 5000억원은 현지 대출로 충당. 연 IRR 7.5% 이상 추정."
        ),
        "output": {
            "investor": {
                "name": (
                    "한화생명(앵커) 외 교보생명·NH생명·신협·삼성증권·HMC투자증권 등 "
                    "기관 컨소시엄 (이지스자산운용 운용)"
                ),
                "type": "보험사",
                "is_direct": False,
            },
            "target_asset": {
                "category": "부동산",
                "assets": [
                    {
                        "sub_type": "오피스",
                        "location": "해외, 프랑스 파리",
                        "asset_name": "사노피 파리 사옥",
                        "tenants": [
                            {
                                "name": "사노피",
                                "type": "제약사",
                                "lease_years_remaining": None,
                            }
                        ],
                    },
                    {
                        "sub_type": "오피스",
                        "location": "해외, 미국 워싱턴",
                        "asset_name": "美 법무부 워싱턴 청사",
                        "tenants": [
                            {
                                "name": "美 법무부",
                                "type": "정부기관",
                                "lease_years_remaining": None,
                            }
                        ],
                    },
                    {
                        "sub_type": "오피스",
                        "location": "해외, 캐나다 몬트리올",
                        "asset_name": "벨캐나다 몬트리올 사옥",
                        "tenants": [
                            {
                                "name": "벨캐나다",
                                "type": "통신사",
                                "lease_years_remaining": None,
                            }
                        ],
                    },
                ],
            },
            "deal_structure": {
                "instrument": "혼합",
                "vehicle": "펀드",
                "ownership_pct": None,
                "loan_amount": 5000,
                "ltv_pct": None,
                "tranche_position": None,
            },
            "return_structure": {
                "type": "혼합",
                "expected_return_pct": 7.5,
                "maturity": "임차 기간 10년 이상 잔존 (펀드 만기 자체는 기사에 명시 안 됨)",
            },
            "deal_status": {
                "current_state": "정상",
                "event_summary": None,
                "realized_loss": None,
            },
            "confidence": {
                "overall": "low",
                "notes": (
                    "① 참여 기관이 보험사·신협·증권사로 혼합되어 앵커인 한화생명 기준 '보험사'로 "
                    "표기함 (규칙 6). ② '선순위·후순위 구분 투자'가 지분 내 우선순위인지 대출 "
                    "트랜치인지 불명확해 instrument를 '혼합'으로, tranche_position은 null로 둠 "
                    "(규칙 7). ③ 파리·워싱턴·몬트리올 3개 자산을 한 번에 매입하는 패키지 딜이라 "
                    "target_asset.assets에 자산별로 별도 원소를 만들어 나열함 (규칙 8). ④ 대출 "
                    "5000억/총액 1조원으로 LTV 50% 역산 가능하나 원문에 'LTV' 표현이 없어 null 유지 "
                    "(규칙 9). ⑤ 각 건물의 임차인(사노피·美 법무부·벨캐나다)은 기사에 명시되어 해당 "
                    "자산 원소의 tenants에 1:1로 매핑해 기재하되, 건물별 잔여 임차기간은 원문에 "
                    "'10년 이상 잔존'이라는 전체 수치만 있고 건물별 수치가 없어 각 tenant의 "
                    "lease_years_remaining은 null로 둠 (규칙 2, 9)."
                ),
            },
            "source_evidence": (
                "국내 큰손들이 5000억원가량을 후순위·선순위로 구분 투자하고 나머지 5000억원은 "
                "현지 대출로 충당하며, 한화생명이 2500억원 규모 앵커 투자자로 참여한다고 보도됨. "
                "연간 수익률(IRR)은 평균 7.5% 이상으로 추정된다고 명시됨."
            ),
        },
    },
    {
        "article": (
            "기사 요지: 한화생명이 계열사 한화호텔앤드리조트가 보유한 서울 소공동 한화빌딩\n"
            "지분 30%를 803억원에 매수해 기존 70%에서 지분 100%를 보유하게 됨. 같은 기사에서\n"
            "사모펀드 운용사 센트로이드인베스트먼트 지분 인수 검토 건도 함께 언급됨."
        ),
        "output": {
            "investor": {
                "name": "한화생명 (매도자: 한화호텔앤드리조트, 계열사 간 거래)",
                "type": "보험사",
                "is_direct": True,
            },
            "target_asset": {
                "category": "부동산",
                "assets": [
                    {
                        "sub_type": "오피스",
                        "location": "국내, 서울 소공동",
                        "asset_name": "소공동 한화빌딩",
                        "tenants": None,
                    }
                ],
            },
            "deal_structure": {
                "instrument": "지분투자",
                "vehicle": "직접보유",
                "ownership_pct": 30,
                "loan_amount": None,
                "ltv_pct": None,
                "tranche_position": None,
            },
            "return_structure": {
                "type": "혼합",
                "expected_return_pct": None,
                "maturity": None,
            },
            "deal_status": {
                "current_state": "정상",
                "event_summary": None,
                "realized_loss": None,
            },
            "confidence": {
                "overall": "low",
                "notes": (
                    "① 이 기사는 두 개의 별개 딜(센트로이드PE 지분 인수 검토 + 소공동빌딩 지분 "
                    "인수)을 함께 다룸. 센트로이드PE는 사모펀드 운용사 지분 투자로 부동산/인프라 "
                    "자산이 아니라 스키마 범위 밖이라 제외하고 소공동빌딩 건만 추출함 (규칙 10). "
                    "② 매도자가 계열사(한화호텔앤드리조트)인 계열사 간 거래(related-party "
                    "transaction)임. ③ ownership_pct는 이번 거래로 취득한 지분율(30%)만 기재함. "
                    "거래 완료 후 한화생명의 최종 보유 지분은 기존 70%+이번 30%=100%임 (규칙 11). "
                    "④ return_structure.type을 '혼합'으로 표기: 리모델링을 통한 임대 경쟁력 제고"
                    "(임대수익형)와 장기적 매각을 통한 투자 회수 가능성(캐피탈게인형)이 모두 언급됨. "
                    "⑤ 수치 정보(expected_return_pct, maturity) 없음."
                ),
            },
            "source_evidence": (
                "한화생명이 한화호텔앤드리조트가 보유한 소공동 한화빌딩 지분 30%를 803억원에 "
                "매수해 기존 70%에서 지분 100%를 보유하게 됐다고 보도됨. 리모델링을 통한 자산가치 "
                "상승과 향후 매각을 통한 투자 회수 가능성이 언급됨."
            ),
        },
    },
    {
        "article": (
            "기사 요지: 우리·NH농협·수협은행과 미래에셋·NH투자증권이 한강자산운용을 통해\n"
            "2019년 뉴욕 브루클린 '500 메트로폴리탄' 개발사업에 1억3300만달러(약 1865억원)\n"
            "규모 대출 펀드를 조성했으나, 차주가 만기(2023년 6월) 이후에도 상환하지 않아\n"
            "기한이익상실(EOD)이 발생. 국내 기관들은 소송 대신 원금 손실을 감수하고\n"
            "해당 대출 채권을 제3자에 매각하기로 함."
        ),
        "output": {
            "investor": {
                "name": (
                    "우리은행·NH농협은행·수협은행·미래에셋증권·NH투자증권 "
                    "(한강자산운용 조성 펀드 출자)"
                ),
                "type": "은행",
                "is_direct": False,
            },
            "target_asset": {
                "category": "부동산",
                "assets": [
                    {
                        "sub_type": "호텔·주거복합",
                        "location": "해외, 미국 뉴욕 브루클린 윌리엄스버그",
                        "asset_name": "500 메트로폴리탄",
                        "tenants": None,
                    }
                ],
            },
            "deal_structure": {
                "instrument": "혼합",
                "vehicle": "펀드",
                "ownership_pct": None,
                "loan_amount": 1865,
                "ltv_pct": None,
                "tranche_position": None,
            },
            "return_structure": {
                "type": "이자수익형",
                "expected_return_pct": None,
                "maturity": "만기 2023년 6월 (경과됨, EOD 발생)",
            },
            "deal_status": {
                "current_state": "매각처분",
                "event_summary": (
                    "차주가 만기(2023년 6월) 이후 리파이낸싱 등을 통한 채무 상환 의지를 보이지 "
                    "않아 기한이익상실(EOD)이 발생. 국내 출자 기관들은 소송을 통한 채권 회수 "
                    "대신, 원금에 미치지 못하는 가격에라도 해당 대출 채권을 제3자에 매각해 "
                    "거래를 종결하는 방식을 선택함."
                ),
                "realized_loss": None,
            },
            "confidence": {
                "overall": "low",
                "notes": (
                    "① instrument enum(선순위대출/후순위·메자닌대출)이 강제 선택 항목인데 "
                    "기사에 트랜치 구분이 없어 '혼합'으로 처리함. ② investor.type enum에 "
                    "'은행'을 추가해 사용함 (규칙: 실제 출자자 구성과 맞지 않는 카테고리를 억지로 "
                    "선택하지 않음). 각 기관별 출자 비중이 기사에 없어 앵커 기준 판단(규칙 6)도 "
                    "적용 불가. ③ 이 기사는 딜의 최초 설계가 아니라 최초 대출 실행(2019년) 이후 "
                    "발생한 채무불이행과 손실 국면을 다루므로 deal_status를 채움 (규칙 12). "
                    "deal_structure.loan_amount는 2019년 최초 대출 원금(1865억원)을 기재하고, "
                    "연체이자 포함 회수해야 할 금액(약 1억7000만달러)이나 실제 매각가는 기사에 "
                    "구체 수치가 없어 deal_status.realized_loss는 null로 둠. ④ target_asset."
                    "sub_type에 '호텔·주거복합'을 사용함 — 기존 enum(오피스/물류센터/데이터센터/"
                    "발전소/도로)에 해당 사항이 없어 새 카테고리로 기재함."
                ),
            },
            "source_evidence": (
                "한강자산운용이 조성한 1억3300만달러 규모 대출 펀드에서 손실이 발생할 것으로 "
                "보이며, 차주의 기한이익상실(EOD)로 만기가 지났음에도 상환이 안 돼 국내 기관들이 "
                "원금 손실을 감수하고 채권을 제3자에 매각하기로 했다고 보도됨."
            ),
        },
    },
]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "investor": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["보험사", "은행", "자산운용사", "SPC/PFV", "기타"],
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
                "assets": {
                    "type": "array",
                    "description": (
                        "매입 대상 자산 목록. 단일 자산 딜이면 원소 1개, 패키지 딜이면 "
                        "자산별로 별도 원소를 넣는다."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "sub_type": {
                                "type": ["string", "null"],
                                "description": (
                                    "예: 오피스, 물류센터, 데이터센터, 발전소, 도로, "
                                    "호텔·주거복합 등"
                                ),
                            },
                            "location": {
                                "type": ["string", "null"],
                                "description": "국내/해외, 도시명",
                            },
                            "asset_name": {"type": ["string", "null"]},
                            "tenants": {
                                "type": ["array", "null"],
                                "description": (
                                    "이 자산의 임차인 정보가 기사에 없거나 해당 딜에 "
                                    "임차인 개념이 없으면 null"
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "type": {
                                            "type": ["string", "null"],
                                            "enum": [
                                                "제약사",
                                                "정부기관",
                                                "통신사",
                                                "기타",
                                                None,
                                            ],
                                        },
                                        "lease_years_remaining": {
                                            "type": ["number", "null"]
                                        },
                                    },
                                    "required": [
                                        "name",
                                        "type",
                                        "lease_years_remaining",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["sub_type", "location", "asset_name", "tenants"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["category", "assets"],
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
        "deal_status": {
            "type": "object",
            "properties": {
                "current_state": {
                    "type": "string",
                    "enum": ["정상", "연체", "채무불이행(EOD)", "매각처분", "만기연장", "회수완료"],
                },
                "event_summary": {
                    "type": ["string", "null"],
                    "description": "무슨 일이 있었는지 요약",
                },
                "realized_loss": {
                    "type": ["number", "null"],
                    "description": "단위: 억원. 확정/예상 손실액",
                },
            },
            "required": ["current_state", "event_summary", "realized_loss"],
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
        "deal_status",
        "confidence",
        "source_evidence",
    ],
    "additionalProperties": False,
}

_DIAGRAM_STYLE = """
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 40px 24px;
      background: #f6f7f8;
      font-family: -apple-system, "Segoe UI", Pretendard, "Malgun Gothic", sans-serif;
      color: #111315;
    }
    .diagram {
      display: flex;
      flex-direction: column;
      align-items: center;
      max-width: 1000px;
      margin: 0 auto;
    }
    .card {
      border-radius: 10px;
      padding: 14px 20px;
      text-align: center;
      box-shadow: 0 1px 2px rgba(17, 19, 21, 0.12);
    }
    .card .label {
      font-size: 12px;
      opacity: 0.75;
      margin-bottom: 2px;
    }
    .card .title {
      font-size: 15px;
      font-weight: 600;
      line-height: 1.35;
    }
    .investor-card { background: #24313a; color: #ffffff; min-width: 220px; max-width: 480px; }
    .vehicle-card { background: #4d5964; color: #ffffff; min-width: 180px; }
    .asset-card { background: #afc5e0; color: #111315; min-width: 180px; max-width: 260px; }
    .connector-v { width: 2px; height: 24px; background: #b1b8bd; }
    .connector-h {
      height: 2px;
      background: #b1b8bd;
      width: 100%;
      max-width: 720px;
    }
    .fan {
      display: flex;
      flex-direction: column;
      align-items: center;
      width: 100%;
    }
    .assets-row {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 28px;
      width: 100%;
      padding: 0 8px;
      border-top: 2px solid #e0e3e5;
      margin-top: 4px;
    }
    .asset-column {
      display: flex;
      flex-direction: column;
      align-items: center;
      margin-top: 20px;
    }
    .asset-column > .connector-v { height: 20px; margin-bottom: 0; }
    .tenants-row {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px;
      max-width: 260px;
      margin-top: 8px;
    }
    .tenant-chip {
      background: #d9ef57;
      color: #111315;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;
    }
    .status-badge {
      display: inline-block;
      border-radius: 999px;
      padding: 8px 20px;
      font-size: 14px;
      font-weight: 700;
      margin-top: 8px;
    }
    .status-badge.normal { background: #e0e3e5; color: #4d5964; }
    .status-badge.alert { background: #f37321; color: #ffffff; }
    .divider {
      width: 100%;
      max-width: 720px;
      height: 1px;
      background: #e0e3e5;
      margin: 28px 0 4px;
    }
"""


def _asset_card_html(asset: dict) -> str:
    sub_type = asset.get("sub_type")
    location = asset.get("location")
    asset_name = asset.get("asset_name")
    tenants = asset.get("tenants")

    title = html.escape(asset_name or sub_type or "자산 미상")
    detail_bits = [b for b in (sub_type, location) if b]
    detail = html.escape(" · ".join(detail_bits)) if detail_bits else ""

    card = f"""
      <div class="asset-column">
        <div class="connector-v"></div>
        <div class="card asset-card">
          <div class="label">{detail}</div>
          <div class="title">{title}</div>
        </div>"""

    if tenants:
        chips = "".join(
            '<span class="tenant-chip" title="{title_attr}">{name}</span>'.format(
                title_attr=html.escape(
                    " · ".join(
                        b
                        for b in (
                            t.get("type"),
                            (
                                f"잔여 {t['lease_years_remaining']}년"
                                if t.get("lease_years_remaining") is not None
                                else None
                            ),
                        )
                        if b
                    )
                ),
                name=html.escape(t.get("name") or "임차인"),
            )
            for t in tenants
        )
        card += f'\n        <div class="tenants-row">{chips}</div>'

    card += "\n      </div>"
    return card


def render_diagram(result: dict) -> str:
    """결과 JSON(investor -> vehicle -> assets -> tenants -> deal_status)을
    세로 계층 구조의 HTML 관계도로 변환한다. 외부 라이브러리 없이 flexbox만 사용."""
    investor = result.get("investor") or {}
    deal_structure = result.get("deal_structure") or {}
    target_asset = result.get("target_asset") or {}
    assets = target_asset.get("assets") or []
    deal_status = result.get("deal_status") or {}

    investor_name = html.escape(investor.get("name") or "투자자 미상")
    investor_sub_bits = [
        b
        for b in (
            investor.get("type"),
            "직접투자" if investor.get("is_direct") else "간접투자 (SPC/펀드)",
        )
        if b
    ]
    investor_sub = html.escape(" · ".join(investor_sub_bits))

    vehicle = html.escape(deal_structure.get("vehicle") or "구조 미상")
    instrument = html.escape(deal_structure.get("instrument") or "")

    asset_columns = "".join(_asset_card_html(a) for a in assets)
    fan_connector = '<div class="connector-h"></div>' if len(assets) > 1 else ""

    current_state = deal_status.get("current_state") or "정상"
    status_class = "normal" if current_state == "정상" else "alert"
    event_summary = deal_status.get("event_summary")
    status_title = f' title="{html.escape(event_summary)}"' if event_summary else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>딜 구조 관계도</title>
<style>{_DIAGRAM_STYLE}</style>
</head>
<body>
  <div class="diagram">
    <div class="card investor-card">
      <div class="label">{investor_sub}</div>
      <div class="title">{investor_name}</div>
    </div>
    <div class="connector-v"></div>
    <div class="card vehicle-card">
      <div class="label">{instrument}</div>
      <div class="title">{vehicle}</div>
    </div>
    <div class="connector-v"></div>
    <div class="fan">
      {fan_connector}
      <div class="assets-row">
        {asset_columns}
      </div>
    </div>
    <div class="divider"></div>
    <span class="status-badge {status_class}"{status_title}>{html.escape(current_state)}</span>
  </div>
</body>
</html>
"""


def build_messages(article_text: str) -> list[dict]:
    """FEW_SHOT_EXAMPLES를 user/assistant 턴으로 펼치고 실제 기사를 마지막 user 턴으로 붙인다."""
    messages = []
    for example in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": example["article"]})
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(example["output"], ensure_ascii=False, indent=2),
            }
        )
    messages.append({"role": "user", "content": article_text})
    return messages


def infer_deal_structure(article_text: str) -> dict:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=build_messages(article_text),
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
        messages = build_messages(article_text)
        print(f"[dry-run] model: {MODEL}")
        print(f"[dry-run] system prompt:\n{SYSTEM_PROMPT}")
        print(f"[dry-run] messages ({len(messages)}개, few-shot {len(FEW_SHOT_EXAMPLES)}쌍 + 실제 기사 1개):")
        for i, message in enumerate(messages):
            print(f"--- messages[{i}] role={message['role']} ---")
            print(message["content"])

        # render_diagram()을 API 호출 없이 검증하기 위해 기존 few-shot 예시 출력을
        # mock JSON으로 재사용한다 (M25 = 자산 1개, 파리·워싱턴·몬트리올 = 자산 3개).
        outputs_dir = pathlib.Path("outputs")
        outputs_dir.mkdir(exist_ok=True)
        mock_cases = [
            ("dry_run_diagram_1asset.html", FEW_SHOT_EXAMPLES[1]["output"]),
            ("dry_run_diagram_3assets.html", FEW_SHOT_EXAMPLES[2]["output"]),
        ]
        for filename, mock_result in mock_cases:
            out_path = outputs_dir / filename
            out_path.write_text(render_diagram(mock_result), encoding="utf-8")
            print(f"[dry-run] render_diagram() mock 출력 저장: {out_path}")
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

    outputs_dir = pathlib.Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    diagram_path = outputs_dir / "result.html"
    diagram_path.write_text(render_diagram(result), encoding="utf-8")
    print(f"관계도 저장: {diagram_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
