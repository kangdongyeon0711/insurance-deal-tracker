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
6. 참여 기관 유형이 보험사·공제회·증권사·신협 등으로 혼합되어 있으면,
   investor.type은 앵커(최대) 투자자 기준으로 정하고, 나머지 기관 구성은
   investor.name에 병기하세요. confidence.notes에도 컨소시엄 구성이 혼합임을 밝히세요.
7. "선순위/후순위로 구분 투자"라는 표현이 지분 내 우선순위 구조(우선주 등)를
   의미하는지, 대출 트랜치를 의미하는지 기사만으로 불명확하면 instrument를 "혼합"으로
   표기하세요. 이때 tranche_position은 전체 딜 구조상 존재하는 트랜치 종류만 기술하고,
   특정 투자자(예: 앵커 투자자)가 그중 어디에 속하는지는 기사에 명시되지 않은 한 null로 두세요.
8. 하나의 딜에서 여러 자산(다른 도시·다른 건물 등)을 한 번에 매입하는 "패키지 딜"인 경우,
   target_asset.asset_name과 location에 해당 자산들을 모두 나열하고,
   confidence.notes에 "패키지 딜"임을 명시하세요.
9. 기사에 나온 다른 숫자들로 계산 가능한 값(예: 대출액 ÷ 총투자액 = LTV)이라도,
   기사 원문에 해당 용어(LTV 등)가 직접 쓰이지 않았다면 해당 필드는 null로 두고,
   confidence.notes에 "계산상 추정 가능하나 원문에 명시되지 않음"이라고 밝히세요.
   임의로 계산한 값을 필드에 채워 넣지 마세요.
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

---

기사 요지: 현대해상·NH농협생명·한화손보·지방행정공제회·KB손보 등 국내 보험사·공제회가
영국 M25 고속도로 운영사(코넥트플러스) 지분 20%를 약 2800억원에 공동 인수함.
하나금융투자·한화투자증권이 총액인수 후 셀다운, 미래에셋자산운용·한화자산운용이
재간접펀드를 운용. 잔여 계약기간 22년 동안 연 6%대 수익률 기대.

```json
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
```

> 참고: 이 예시는 "진짜 인프라 지분투자" 케이스이며, vehicle이 펀드/SPC 중
> 무엇인지 기사만으로 완전히 단정할 수 없어 confidence가 medium으로 나온
> 전형적인 사례입니다. 딜 주선사(총액인수·셀다운)와 자산운용사(재간접펀드 운용)의
> 역할이 분리되어 있을 때 vehicle 판단이 어떻게 이뤄지는지 보여줍니다.

---

기사 요지: 한화생명을 앵커 투자자로 교보생명·NH생명·신협·삼성증권·HMC투자증권 등
기관투자가들이 이지스자산운용을 통해 파리·워싱턴·몬트리올 소재 오피스 빌딩 3곳을
약 1조원(패키지)에 매입. 5000억원은 국내 기관이 선순위·후순위로 구분 투자,
나머지 5000억원은 현지 대출로 충당. 연 IRR 7.5% 이상 추정.

```json
{
  "investor": {
    "name": "한화생명(앵커) 외 교보생명·NH생명·신협·삼성증권·HMC투자증권 등 기관 컨소시엄 (이지스자산운용 운용)",
    "type": "보험사",
    "is_direct": false
  },
  "target_asset": {
    "category": "부동산",
    "sub_type": "오피스",
    "location": "해외, 파리·워싱턴·몬트리올 (3개국 패키지 매입)",
    "asset_name": "사노피 파리 사옥, 美 법무부 워싱턴 청사, 벨캐나다 몬트리올 사옥 (3건 패키지)"
  },
  "deal_structure": {
    "instrument": "혼합",
    "vehicle": "펀드",
    "ownership_pct": null,
    "loan_amount": 5000,
    "ltv_pct": null,
    "tranche_position": null
  },
  "return_structure": {
    "type": "혼합",
    "expected_return_pct": 7.5,
    "maturity": "임차 기간 10년 이상 잔존 (펀드 만기 자체는 기사에 명시 안 됨)"
  },
  "confidence": {
    "overall": "low",
    "notes": "① 참여 기관이 보험사·신협·증권사로 혼합되어 앵커인 한화생명 기준 '보험사'로 표기함 (규칙 6). ② '선순위·후순위 구분 투자'가 지분 내 우선순위인지 대출 트랜치인지 불명확해 instrument를 '혼합'으로, tranche_position은 null로 둠 (규칙 7). ③ 파리·워싱턴·몬트리올 3개 자산을 한 번에 매입하는 패키지 딜임 (규칙 8). ④ 대출 5000억/총액 1조원으로 LTV 50% 역산 가능하나 원문에 'LTV' 표현이 없어 null 유지 (규칙 9)."
  },
  "source_evidence": "국내 큰손들이 5000억원가량을 후순위·선순위로 구분 투자하고 나머지 5000억원은 현지 대출로 충당하며, 한화생명이 2500억원 규모 앵커 투자자로 참여한다고 보도됨. 연간 수익률(IRR)은 평균 7.5% 이상으로 추정된다고 명시됨."
}
```

> 참고: 이 예시는 컨소시엄 구성이 혼합이고, instrument가 지분/대출 중 무엇인지
> 불명확하며, 여러 자산을 한 번에 매입하는 패키지 딜이라 confidence가 low로
> 나온 케이스입니다. 규칙 6~9가 추가된 계기가 된 예시입니다.

## 다음 액션 (Claude Code에서 할 일)

1. Claude Code를 열고 새 프로젝트 폴더 생성 (예: `insurance-deal-tracker`)
2. 이 파일을 프로젝트 폴더에 넣기
3. Claude Code에게 이렇게 요청:
   "이 스키마와 프롬프트를 바탕으로, 기사 텍스트를 입력받아 Claude API를 호출해서
   JSON을 반환하는 파이썬 스크립트를 만들어줘. 입력은 일단 커맨드라인 인자로 받아."
4. 실제 기사 2~3개를 텍스트로 붙여넣어 테스트 → 결과가 이상하면
   프롬프트의 규칙 섹션을 같이 수정
