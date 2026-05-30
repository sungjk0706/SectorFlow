# -*- coding: utf-8 -*-
"""
키움증권 매매부적격종목 필터링 (바이블 기준)
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def is_trading_eligible(item: dict) -> tuple[bool, str]:
    """
    ka10099 응답 item을 기반으로 매매적격 여부 판별.
    
    Args:
        item: ka10099 응답 개별 종목 dict
        
    Returns:
        (적격여부, 제외사유) 튜플
    """
    # 필수 필드 추출
    code = str(item.get('code', '')).strip()
    name = str(item.get('name', '')).lower()
    market = str(item.get('marketCode', '')).strip()
    order_warning = str(item.get('orderWarning', '0')).strip()
    state = str(item.get('state', '')).lower()
    audit = str(item.get('auditInfo', '')).lower()
    nxt = str(item.get('nxtEnable', 'N')).strip().upper()
    list_count = str(item.get('listCount', '')).strip()
    reg_day = str(item.get('regDay', '')).strip()
    last_price = str(item.get('lastPrice', '')).strip()
    market_name = str(item.get('marketName', '')).lower()
    company_class = str(item.get('companyClassName', '')).lower()
    
    # 1) 시장 허용: 코스피(0), 코스닥(10)만 허용
    if market not in ['0', '10']:
        return False, f"시장구분 미허용: {market}"
    
    # 2) 비주식 분류: ETF, ETN, ELW, 리츠, REIT, K-OTC, SPAC 제외
    non_equity_keywords = ['etf', 'etn', 'elw', '리츠', 'reit', 'k-otc', 'kots', 'spac']
    if any(k in name for k in non_equity_keywords):
        return False, f"비주식 분류: {name}"
    if any(k in market_name for k in non_equity_keywords):
        return False, f"비주식 시장: {market_name}"
    
    # 3) 투자유의종목: orderWarning이 0이 아니면 제외
    if order_warning and order_warning != '0':
        return False, f"투자유의종목: orderWarning={order_warning}"
    
    # 4) 종목상태: 금지 키워드 포함 시 제외
    forbidden_states = [
        '관리종목', '거래정지', '불성실공시', '상장폐지', 
        '정리매매', '투자경고', '투자위험', '상장폐지예고', '증거금100%'
    ]
    for keyword in forbidden_states:
        if keyword.lower() in state:
            return False, f"종목상태: {state}"
    
    # 5) 감리구분: '정상' 이외 제외
    if audit and '정상' not in audit:
        return False, f"감리구분: {audit}"
    
    # 6) 스팩/SPAC 제외
    if 'spac' in name or '스팩' in name:
        return False, f"스팩: {name}"
    
    # 7) 우선주 판별
    preferred_keywords = ['우선주', '우', '우b', '우b', 'pref', 'prefer']
    if any(k in name for k in preferred_keywords):
        return False, f"우선주: {name}"
    if company_class and any(k in company_class for k in preferred_keywords):
        return False, f"우선주(회사분류): {company_class}"
    
    # 8) 상장주식수 비정상값 제외
    if list_count and list_count.startswith('0000000000000000'):
        return False, f"상장주식수 비정상: {list_count}"
    
    # 9) 전일종가 비정상값 제외
    if last_price and (last_price == '00000000' or last_price == '0'):
        return False, f"전일종가 비정상: {last_price}"
    
    # 10) NXT 중복상장: 필터링하지 않음 (단순 정보)
    # nxt는 거래 가능 여부 판단에 사용하지 않음
    
    # 모든 조건 통과 시 적격
    return True, ""
