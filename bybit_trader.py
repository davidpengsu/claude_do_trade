import logging
import time
from typing import Dict, Any, Optional

from bybit_client import BybitClient

class BybitTrader:
    """
    Bybit 트레이딩 실행 클래스
    
    실행 서버에서 바이비트 거래를 실행하는 전문화된 기능 제공
    """
    
    def __init__(self, symbol: str, api_key: str, api_secret: str, trade_settings: Dict[str, Any]):
        """
        BybitTrader 초기화
        
        Args:
            symbol: 거래 심볼 (예: "BTCUSDT")
            api_key: Bybit API 키
            api_secret: Bybit API 시크릿
            trade_settings: 거래 설정
        """
        self.symbol = symbol
        self.client = BybitClient(api_key, api_secret)
        self.trade_settings = trade_settings
        
        # 로거 설정
        self.logger = logging.getLogger(f"bybit_trader_{symbol}")
        
        # 심볼 정보 캐시
        self.symbol_info = None
        self.update_symbol_info()
    
    def update_symbol_info(self) -> None:
        """심볼 정보 업데이트"""
        try:
            self.symbol_info = self.client.get_symbol_info(self.symbol)
            self.logger.info(f"{self.symbol} 심볼 정보 업데이트 완료")
        except Exception as e:
            self.logger.error(f"심볼 정보 업데이트 실패: {e}")
    
    def get_current_position(self) -> Optional[Dict[str, Any]]:
        """
        현재 포지션 조회
        
        Returns:
            포지션 정보 또는 포지션이 없는 경우 None
        """
        try:
            position = self.client.get_positions(self.symbol)
            if position.get("exists", False):
                return position
            return None
        except Exception as e:
            self.logger.error(f"포지션 정보 조회 중 오류 발생: {e}")
            return None
    
    def open_position(self, position_type: str) -> Dict[str, Any]:
        """
        새로운 포지션 진입
        
        Args:
            position_type: 포지션 타입 ("long" 또는 "short")
            
        Returns:
            성공 여부 및 상세 정보가 포함된 결과
        """
        try:
            # 포지션 타입에 따른 매수/매도 방향 설정
            side = "Buy" if position_type.lower() == "long" else "Sell"
            
            # 현재 가격 확인
            current_price = self.client.get_current_price(self.symbol)
            
            # 레버리지 설정
            leverage = self.trade_settings.get("leverage", 5)
            self.client.set_leverage(self.symbol, leverage)
            
            # 주문 수량 계산
            position_size_mode = self.trade_settings.get("position_size_mode", "percent")
            position_size_value = (
                self.trade_settings.get("position_size_fixed", 100.0) 
                if position_size_mode == "fixed" 
                else self.trade_settings.get("position_size_percent", 10.0)
            )
            
            qty = self.client.calculate_order_quantity(
                symbol=self.symbol,
                position_size_mode=position_size_mode,
                position_size_value=position_size_value,
                leverage=leverage,
                current_price=current_price
            )
            
            # 시장가 주문 실행
            order_result = self.client.place_market_order(
                symbol=self.symbol,
                side=side,
                qty=str(qty)
            )
            
            if order_result.get("retCode") != 0:
                return {
                    "success": False,
                    "message": f"주문 실패: {order_result.get('retMsg', '알 수 없는 오류')}",
                    "order_id": None
                }
            
            # 주문 ID 확인
            order_id = order_result.get("result", {}).get("orderId")
            
            # 주문 체결 대기
            time.sleep(2)
            
            # 포지션 정보 확인
            position = self.get_current_position()
            if not position:
                return {
                    "success": False,
                    "message": "주문은 실행되었으나 포지션이 생성되지 않음",
                    "order_id": order_id
                }
            
            # 성공 결과 반환
            return {
                "success": True,
                "message": f"{self.symbol} {position_type} 포지션 진입 성공",
                "order_id": order_id,
                "entry_price": position.get("entry_price"),
                "size": qty,
                "leverage": leverage
            }
            
        except Exception as e:
            self.logger.error(f"포지션 진입 중 오류 발생: {e}")
            return {
                "success": False,
                "message": f"포지션 진입 중 오류 발생: {str(e)}",
                "order_id": None
            }
    
    def close_position(self) -> Dict[str, Any]:
        """
        현재 포지션 청산
        
        Returns:
            성공 여부 및 상세 정보가 포함된 결과
        """
        try:
            # 현재 포지션 확인
            position = self.get_current_position()
            if not position:
                return {
                    "success": True,
                    "message": f"{self.symbol} 활성 포지션 없음",
                    "order_id": None
                }
            
            # 포지션 청산
            close_result = self.client.close_position(self.symbol)
            
            if not close_result.get("success", False):
                return {
                    "success": False,
                    "message": close_result.get("message", "포지션 청산 실패"),
                    "order_id": None
                }
            
            # 관련 주문 모두 취소
            self.client.cancel_all_orders(self.symbol)
            
            # 현재 가격 확인
            current_price = self.client.get_current_price(self.symbol)
            
            return {
                "success": True,
                "message": f"{self.symbol} 포지션 청산 성공",
                "price": current_price,
                "order_id": close_result.get("order_id")  # 주문 ID 전달
            }
            
        except Exception as e:
            self.logger.error(f"포지션 청산 중 오류 발생: {e}")
            return {
                "success": False,
                "message": f"포지션 청산 중 오류 발생: {str(e)}",
                "order_id": None
            }
    
    def set_tp_sl(self, entry_price: float, position_type: str) -> Dict[str, Any]:
        """
        포지션의 TP/SL 설정
        
        Args:
            entry_price: 진입 가격
            position_type: 포지션 타입 ("long" 또는 "short")
            
        Returns:
            성공 여부 및 상세 정보가 포함된 결과
        """
        try:
            # 설정에 따른 TP/SL 가격 계산
            tp_percent = self.trade_settings.get("tp_percent", 3.0)
            sl_percent = self.trade_settings.get("sl_percent", 1.5)
            
            if position_type.lower() == "long":
                tp_price = entry_price * (1 + tp_percent / 100)
                sl_price = entry_price * (1 - sl_percent / 100)
            else:  # short
                tp_price = entry_price * (1 - tp_percent / 100)
                sl_price = entry_price * (1 + sl_percent / 100)
            
            # TP/SL 설정
            result = self.client.set_tp_sl(self.symbol, tp_price, sl_price)
            
            if not result:
                return {
                    "success": False,
                    "message": "TP/SL 설정 실패",
                    "take_profit": None,
                    "stop_loss": None
                }
            
            return {
                "success": True,
                "message": f"TP/SL 설정 완료: TP={tp_price}, SL={sl_price}",
                "take_profit": tp_price,
                "stop_loss": sl_price
            }
            
        except Exception as e:
            self.logger.error(f"TP/SL 설정 중 오류 발생: {e}")
            return {
                "success": False,
                "message": f"TP/SL 설정 중 오류 발생: {str(e)}",
                "take_profit": None,
                "stop_loss": None
            }
