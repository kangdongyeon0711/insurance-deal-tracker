# 보험사 부동산·인프라 투자 딜 구조 추론 — 프롬프트 초안

## 1. 출력 스키마 (JSON)

```json
{
  "investor": {
    "name": "string",
    "type": "보험사 | 자산운용사 | SPC/PFV | 기타",
    "is_direct": "boolean (보험사가 직접 투자하는지, SPC/펀드를 통한 간접투자인지)"
  },
  "target_asset": {
    "category": "부동산 | 인프라",
    "sub_type": "오피스 | 물류센터 | 데이터센터 | 발전소 | 도로 등",
    "location": "국내/해외, 도시명",
    "asset_name": "string or null"
  },
  "deal_structure": {
    "instrument": "지분투자 | 선순위대출 | 후순위/메자닌대출 | 채권 | 혼합",
    "vehicle": "직접보유 | SPC | PFV | 리츠 | 펀드",
    "ownership_pct": "number or null",
    "loan_amount": "number or null (단위: 억원)",
    "ltv_pct": "number or null",
    "tranche_position": "선순위 | 중순위 | 후순위 | null"
  },
  "return_structure": {
    "type": "임대수익형 | 이자수익형 | 캐피탈게인형 | 배당형 | 혼합",
    "expected_return_pct": "number or null",
    "maturity": "string or null (예: 5년, 2031년 만기)"
  },
  "confidence": {
    "overall": "high | medium | low",
    "notes": "기사에 명시되지 않아 추론한 부분을 여기 서술"
  },
  "source_evidence": "기사에서 이 구조를 판단한 근거 문장 1~2개 (요약, 직접 인용 금지)"
}
```

## 2. 시스템 프롬프트 초안

```
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
```

## 3. Few-shot 예시 (검색으로 찾은 실제 사례 기반)

기사 요지: 신창재 교보생명 회장이 재무적투자자(FI) 지분을 인수하기 위해
신한투자증권·한국투자증권이 설립한 SPC를 활용, 본인 보유 교보생명 지분을
담보로 주식담보대출을 실행하여 약 4천억 원을 조달함.

```json
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
```

> 참고: 이 예시는 스키마가 "부동산/인프라가 아닌 딜"을 만났을 때 어떻게
> confidence.notes로 걸러내는지 보여주기 위해 일부러 골랐습니다.
> 실제 few-shot에는 진짜 부동산/인프라 투자 기사 2~3개를 더 추가하는 게 좋습니다.

## 다음 액션 (Claude Code에서 할 일)

1. Claude Code를 열고 새 프로젝트 폴더 생성 (예: `insurance-deal-tracker`)
2. 이 파일을 프로젝트 폴더에 넣기
3. Claude Code에게 이렇게 요청:
   "이 스키마와 프롬프트를 바탕으로, 기사 텍스트를 입력받아 Claude API를 호출해서
   JSON을 반환하는 파이썬 스크립트를 만들어줘. 입력은 일단 커맨드라인 인자로 받아."
4. 실제 기사 2~3개를 텍스트로 붙여넣어 테스트 → 결과가 이상하면
   프롬프트의 규칙 섹션을 같이 수정
