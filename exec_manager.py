import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from bybit_trader import BybitTrader
from exec_db_manager import ExecDBManager
from config_loader import ConfigLoader

# 로그 설정
logger = logging.getLogger("exec_manager")

class ExecManager:
    """
    거래 실행 관리 클래스
    
    결정 서버에서 검증된 신호를 받아 실제 거래를 실행하고 관리합니다.
    """
    
    def __init__(self):
        """ExecManager 초기화"""
        # 설정 로드
        self.config = ConfigLoader()
        self.trade_settings = self.config.load_config("trade_settings.json")
        
        # 코인별 Bybit 트레이더 초기화
        self.traders = {}
        
        for symbol in self.config.get_supported_symbols():
            # 해당 코인의 API 키로 Bybit 트레이더 초기화
            bybit_config = self.config.get_bybit_api_key(symbol)
            self.traders[symbol] = BybitTrader(
                symbol,
                bybit_config["key"],
                bybit_config["secret"],
                self.trade_settings
            )
        
        # DB 매니저 초기화
        db_config = self.config.get_db_config()
        self.db_manager = ExecDBManager(
            db_config["host"],
            db_config["user"],
            db_config["password"],
            db_config["database"]
        )
    
    def handle_execution_request(self, request_data: Dict[str, Any], client_ip: str) -> Dict[str, Any]:
        """
        실행 요청 처리
        
        Args:
            request_data: 결정 서버에서 받은 요청 데이터
            client_ip: 클라이언트 IP
            
        Returns:
            처리 결과
        """
        start_time = time.time()
        event_id = request_data.get("eventId", str(uuid.uuid4()))
        symbol = request_data.get("symbol")
        action = request_data.get("action")
        position_type = request_data.get("position_type")
        
        # 요청 로깅
        event_data = {
            "eventId": event_id,
            "eventType": action.upper(),
            "symbol": symbol,
            "positionType": position_type,
            "execStatus": "PENDING",
            "requestTime": datetime.now(),
            "rawRequest": json.dumps(request_data),
            "requestIp": client_ip
        }
        
        self.db_manager.log_execution_event(event_data)
        
        try:
            # 지원하는 심볼 확인
            if symbol not in self.traders:
                return self._handle_error(event_id, f"지원하지 않는 심볼: {symbol}")
            
            trader = self.traders[symbol]
            
            # 액션 타입에 따른 처리
            if action == "OPEN":
                result = self._handle_open_position(trader, event_id, symbol, position_type, request_data)
            elif action == "CLOSE":
                result = self._handle_close_position(trader, event_id, symbol, request_data)
            elif action == "TREND_TOUCH":
                result = self._handle_trend_touch(trader, event_id, symbol, request_data)
            else:
                return self._handle_error(event_id, f"지원하지 않는 액션: {action}")
            
            # 성공 응답
            execution_time = time.time() - start_time
            
            # 이벤트 업데이트
            update_data = {
                "execStatus": result["status"],
                "executionTime": datetime.now(),
                "executionDuration": int(execution_time * 1000)
            }
            
            if result["status"] != "SUCCESS":
                update_data["errorMessage"] = result.get("message", "")
            
            self.db_manager.update_execution_event(event_id, update_data)
            
            return {
                "status": "success",
                "event_id": event_id,
                "execution_time": f"{execution_time:.3f}초",
                "result": result
            }
            
        except Exception as e:
            logger.exception(f"실행 요청 처리 중 오류 발생: {e}")
            return self._handle_error(event_id, f"실행 처리 오류: {str(e)}")
    
    def _handle_open_position(self, trader, event_id, symbol, position_type, request_data):
        """포지션 진입 처리"""
        logger.info(f"{symbol} {position_type} 포지션 진입 요청 처리")
        
        try:
            # 현재 포지션 확인
            current_position = trader.get_current_position()
            
            # 같은 방향 포지션이 이미 있는 경우
            if current_position and current_position["position_type"] == position_type:
                return {
                    "status": "SKIPPED",
                    "message": f"이미 {position_type} 포지션이 있습니다."
                }
            
            # 반대 방향 포지션이 있는 경우 먼저 청산
            if current_position:
                close_result = trader.close_position()
                if not close_result["success"]:
                    return {
                        "status": "FAILED",
                        "message": f"기존 포지션 청산 실패: {close_result['message']}"
                    }
                
                # 포지션 청산 거래 기록
                self.db_manager.log_trade({
                    "tradeId": str(uuid.uuid4()),
                    "eventId": event_id,
                    "symbol": symbol,
                    "orderType": "MARKET",
                    "side": "Sell" if current_position["position_type"] == "long" else "Buy",
                    "positionType": current_position["position_type"],
                    "quantity": current_position["size"],
                    "price": close_result["price"],
                    "leverage": current_position["leverage"],
                    "orderStatus": "FILLED",
                    "bybitOrderId": close_result["order_id"],
                    "executionTime": datetime.now()
                })
            
            # 새 포지션 진입
            open_result = trader.open_position(position_type)
            
            if not open_result["success"]:
                return {
                    "status": "FAILED" if not current_position else "PARTIAL",
                    "message": f"포지션 진입 실패: {open_result['message']}"
                }
            
            # TP/SL 설정
            if open_result["success"]:
                tp_sl_result = trader.set_tp_sl(
                    open_result["entry_price"],
                    position_type
                )
                
                if not tp_sl_result["success"]:
                    logger.warning(f"TP/SL 설정 실패: {tp_sl_result['message']}")
            
            # 거래 기록
            self.db_manager.log_trade({
                "tradeId": str(uuid.uuid4()),
                "eventId": event_id,
                "symbol": symbol,
                "orderType": "MARKET",
                "side": "Buy" if position_type == "long" else "Sell",
                "positionType": position_type,
                "quantity": open_result["size"],
                "price": open_result["entry_price"],
                "leverage": open_result["leverage"],
                "takeProfit": open_result.get("take_profit"),
                "stopLoss": open_result.get("stop_loss"),
                "orderStatus": "FILLED",
                "bybitOrderId": open_result["order_id"],
                "executionTime": datetime.now()
            })
            
            return {
                "status": "SUCCESS",
                "message": f"{symbol} {position_type} 포지션 진입 성공",
                "details": open_result
            }
            
        except Exception as e:
            logger.exception(f"{symbol} 포지션 진입 실행 중 오류 발생: {e}")
            return {
                "status": "FAILED",
                "message": f"포지션 진입 중 오류 발생: {str(e)}"
            }
    
    def _handle_close_position(self, trader, event_id, symbol, request_data):
        """포지션 청산 처리"""
        logger.info(f"{symbol} 포지션 청산 요청 처리")
        
        try:
            # 현재 포지션 확인
            current_position = trader.get_current_position()
            
            if not current_position:
                return {
                    "status": "SKIPPED",
                    "message": f"{symbol} 활성 포지션이 없습니다."
                }
            
            # 포지션 청산
            close_result = trader.close_position()
            
            if not close_result["success"]:
                return {
                    "status": "FAILED",
                    "message": f"포지션 청산 실패: {close_result['message']}"
                }
            
            # 거래 기록
            self.db_manager.log_trade({
                "tradeId": str(uuid.uuid4()),
                "eventId": event_id,
                "symbol": symbol,
                "orderType": "MARKET",
                "side": "Sell" if current_position["position_type"] == "long" else "Buy",
                "positionType": current_position["position_type"],
                "quantity": current_position["size"],
                "price": close_result["price"],
                "leverage": current_position["leverage"],
                "orderStatus": "FILLED",
                "bybitOrderId": close_result["order_id"],
                "executionTime": datetime.now()
            })
            
            return {
                "status": "SUCCESS",
                "message": f"{symbol} {current_position['position_type']} 포지션 청산 성공",
                "details": close_result
            }
            
        except Exception as e:
            logger.exception(f"{symbol} 포지션 청산 실행 중 오류 발생: {e}")
            return {
                "status": "FAILED",
                "message": f"포지션 청산 중 오류 발생: {str(e)}"
            }
    
    def _handle_trend_touch(self, trader, event_id, symbol, request_data):
        """추세선 터치 처리 (추세선 터치로 인한 청산)"""
        logger.info(f"{symbol} 추세선 터치 요청 처리")
        
        try:
            # 현재 포지션 확인
            current_position = trader.get_current_position()
            
            if not current_position:
                return {
                    "status": "SKIPPED",
                    "message": f"{symbol} 활성 포지션이 없습니다."
                }
            
            # AI 결정이 청산(yes)인 경우만 처리
            ai_decision = request_data.get("ai_decision", {})
            if ai_decision.get("Answer", "").lower() != "yes":
                return {
                    "status": "SKIPPED",
                    "message": f"AI 결정이 청산이 아닙니다: {ai_decision.get('Answer')}"
                }
            
            # 포지션 청산
            close_result = trader.close_position()
            
            if not close_result["success"]:
                return {
                    "status": "FAILED",
                    "message": f"포지션 청산 실패: {close_result['message']}"
                }
            
            # 거래 기록
            self.db_manager.log_trade({
                "tradeId": str(uuid.uuid4()),
                "eventId": event_id,
                "symbol": symbol,
                "orderType": "MARKET",
                "side": "Sell" if current_position["position_type"] == "long" else "Buy",
                "positionType": current_position["position_type"],
                "quantity": current_position["size"],
                "price": close_result["price"],
                "leverage": current_position["leverage"],
                "orderStatus": "FILLED",
                "bybitOrderId": close_result["order_id"],
                "additionalInfo": json.dumps({"reason": "trend_touch", "ai_decision": ai_decision}),
                "executionTime": datetime.now()
            })
            
            return {
                "status": "SUCCESS",
                "message": f"{symbol} {current_position['position_type']} 포지션 청산 성공 (추세선 터치)",
                "details": close_result
            }
            
        except Exception as e:
            logger.exception(f"{symbol} 추세선 터치 실행 중 오류 발생: {e}")
            return {
                "status": "FAILED",
                "message": f"추세선 터치 처리 중 오류 발생: {str(e)}"
            }
    
    def _handle_error(self, event_id, error_message):
        """에러 처리 및 로깅"""
        logger.error(error_message)
        
        # 이벤트 업데이트
        if event_id:
            update_data = {
                "execStatus": "FAILED",
                "executionTime": datetime.now(),
                "errorMessage": error_message
            }
            self.db_manager.update_execution_event(event_id, update_data)
        
        return {
            "status": "error",
            "message": error_message
        }