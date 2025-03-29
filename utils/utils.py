import math
import logging
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Tuple, Union, Optional

logger = logging.getLogger("trading_utils")

def round_to_tick(value: float, tick_size: float) -> float:
    """
    특정 틱 사이즈에 맞게 값을 반올림
    
    Args:
        value: 반올림할 값
        tick_size: 틱 사이즈
        
    Returns:
        틱 사이즈에 맞게 반올림된 값
    """
    precision = get_decimal_places(tick_size)
    return math.floor(value / tick_size) * tick_size

def get_decimal_places(value: float) -> int:
    """
    숫자의 소수점 자릿수 계산
    
    Args:
        value: 소수점 자릿수를 계산할 값
        
    Returns:
        소수점 자릿수
    """
    str_value = str(value).rstrip('0').rstrip('.')
    if '.' in str_value:
        return len(str_value.split('.')[1])
    return 0



def calculate_pnl(entry_price: float, exit_price: float, position_type: str, size: float, leverage: int) -> float:
    """
    포지션의 PnL 계산
    
    Args:
        entry_price: 진입 가격
        exit_price: 청산 가격
        position_type: 포지션 타입 ("long" 또는 "short")
        size: 포지션 크기
        leverage: 레버리지
        
    Returns:
        손익 금액
    """
    if position_type.lower() == "long":
        pnl_ratio = (exit_price - entry_price) / entry_price
    else:  # short
        pnl_ratio = (entry_price - exit_price) / entry_price
    
    # 레버리지 적용
    pnl_ratio *= leverage
    
    # 손익 계산 (크기 * 진입가 * 손익률)
    pnl = size * entry_price * pnl_ratio
    
    return pnl

def format_number(value: float, precision: int = 8) -> str:
    """
    숫자를 지정된 소수점 자릿수로 포맷팅
    
    Args:
        value: 포맷팅할 값
        precision: 소수점 자릿수
        
    Returns:
        포맷팅된 문자열
    """
    return f"{value:.{precision}f}".rstrip('0').rstrip('.')

def safe_convert_to_float(value: Optional[Union[str, int, float]]) -> float:
    """
    안전하게 float로 변환
    
    Args:
        value: 변환할 값
        
    Returns:
        변환된 값 또는 오류 시 0.0
    """
    if value is None:
        return 0.0
    
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def calculate_quantity(
    balance: float, 
    position_size_percent: float,
    leverage: int,
    current_price: float,
    min_qty: float,
    step_size: float,
    max_qty: Optional[float] = None
) -> float:
    """
    주문 수량 계산
    
    Args:
        balance: 계좌 잔고
        position_size_percent: 사용할 계좌 잔고 비율
        leverage: 레버리지
        current_price: 현재 가격
        min_qty: 최소 주문 수량
        step_size: 수량 단위
        max_qty: 최대 주문 수량
        
    Returns:
        계산된 주문 수량
    """
    try:
        # 백분율 계산 (예: 10.0 -> 0.1)
        percentage = position_size_percent / 100.0
        
        # 사용 가능한 금액 계산
        available_amount = balance * percentage
        
        # 레버리지 적용
        notional = available_amount * leverage
        
        # 가격으로 나누어 수량 계산
        raw_qty = notional / current_price
        
        # 스텝 사이즈에 맞게 조정
        steps = math.floor(raw_qty / step_size)
        qty = steps * step_size
        
        # 최소 주문 수량 확인
        if qty < min_qty:
            qty = min_qty
        
        # 최대 주문 수량 확인
        if max_qty is not None and qty > max_qty:
            qty = max_qty
        
        return qty
        
    except Exception as e:
        logger.error(f"주문 수량 계산 중 오류 발생: {e}")
        return min_qty  # 오류 시 최소 수량 반환
