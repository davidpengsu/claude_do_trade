import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import threading 
from bybit_trader import BybitTrader
from exec_db_manager import ExecDBManager
from config_loader import ConfigLoader

# 로그 설정
logger = logging.getLogger("exec_manager")

# 거래 상태 상수
TRADE_STATUS_OPEN = "OPEN"       # 포지션 오픈 상태
TRADE_STATUS_FILLED = "FILLED"   # 주문 체결 완료
TRADE_STATUS_CLOSED = "CLOSED"   # 포지션 청산됨
TRADE_STATUS_CANCELED = "CANCELED"  # 주문 취소됨
TRADE_STATUS_REJECTED = "REJECTED"  # 주문 거부됨

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
            if action == "open_position":
                result = self._handle_open_position(trader, event_id, symbol, position_type, request_data)
            elif action == "close_position":
                result = self._handle_close_position(trader, event_id, symbol, request_data)
            elif action == "trend_touch":
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
                trade_id = str(uuid.uuid4())
                self.db_manager.log_trade({
                    "tradeId": trade_id,
                    "eventId": event_id,
                    "symbol": symbol,
                    "orderType": "MARKET",
                    "side": "Sell" if current_position["position_type"] == "long" else "Buy",
                    "positionType": current_position["position_type"],
                    "quantity": current_position["size"],
                    "price": close_result["price"],
                    "leverage": current_position["leverage"],
                    "orderStatus": TRADE_STATUS_FILLED,
                    "bybitOrderId": close_result.get("order_id"),
                    "executionTime": datetime.now()
                })
                
                # 기존 거래 상태 업데이트
                try:
                    # 해당 거래 상태 업데이트
                    with self.db_manager.conn.cursor() as cursor:
                        cursor.execute("UPDATE trades SET orderStatus = %s WHERE symbol = %s AND positionType = %s AND orderStatus = %s", 
                                     [TRADE_STATUS_CLOSED, symbol, current_position["position_type"], TRADE_STATUS_OPEN])
                        self.db_manager.conn.commit()
                except Exception as e:
                    logger.warning(f"이전 거래 상태 업데이트 중 오류 발생: {e}")
            
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
            trade_id = str(uuid.uuid4())
            self.db_manager.log_trade({
                "tradeId": trade_id,
                "eventId": event_id,
                "symbol": symbol,
                "orderType": "MARKET",
                "side": "Buy" if position_type == "long" else "Sell",
                "positionType": position_type,
                "quantity": open_result["size"],
                "price": open_result["entry_price"],
                "leverage": open_result["leverage"],
                "takeProfit": tp_sl_result.get("take_profit") if open_result["success"] and tp_sl_result["success"] else None,
                "stopLoss": tp_sl_result.get("stop_loss") if open_result["success"] and tp_sl_result["success"] else None,
                "orderStatus": TRADE_STATUS_OPEN,  # 여기를 OPEN으로 변경
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
            # 주문 ID 가져오기
            order_id = close_result.get("order_id")
            logger.info(f"포지션 청산 주문 ID: {order_id}")

            # 거래 기록
            trade_id = str(uuid.uuid4())
            self.db_manager.log_trade({
                "tradeId": trade_id,
                "eventId": event_id,
                "symbol": symbol,
                "orderType": "MARKET",
                "side": "Sell" if current_position["position_type"] == "long" else "Buy",
                "positionType": current_position["position_type"],
                "quantity": current_position["size"],
                "price": close_result["price"],
                "leverage": current_position["leverage"],
                "orderStatus": TRADE_STATUS_FILLED,
                "bybitOrderId": order_id,  # 변수로 명시적 사용
                "executionTime": datetime.now()
            })

            # PnL 정보 지연 업데이트를 위한 타이머 시작
            threading.Timer(30.0, lambda: self._update_trade_pnl(trade_id, symbol, close_result.get("order_id"))).start()
            logger.info(f"PnL 정보 지연 업데이트 예약됨 (30초 후): {trade_id}")
            
            # 기존 거래 상태 업데이트
            try:
                # 해당 거래 상태 업데이트
                with self.db_manager.conn.cursor() as cursor:
                    cursor.execute("UPDATE trades SET orderStatus = %s WHERE symbol = %s AND positionType = %s AND orderStatus = %s", 
                                 [TRADE_STATUS_CLOSED, symbol, current_position["position_type"], TRADE_STATUS_OPEN])
                    self.db_manager.conn.commit()
            except Exception as e:
                logger.warning(f"거래 상태 업데이트 중 오류 발생: {e}")
            
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
        
    def _update_trade_pnl(self, trade_id: str = None, symbol: str = None, order_id: str = None):
        """
        거래의 PnL 정보 업데이트 - 직접 API 키를 사용하는 단순 버전
        
        문제를 해결하기 위해 직접 API 요청을 수행하는 방식으로 변경했습니다.
        각 심볼에 맞는 API 키를 직접 사용하여 PnL 정보를 조회합니다.
        
        Args:
            trade_id: (선택) 특정 거래 ID
            symbol: (선택) 심볼
            order_id: (선택) 바이비트 주문 ID
        """
        try:
            import requests
            import time
            import hmac
            import hashlib
            
            # DB 연결 확인
            self.db_manager._ensure_connection()
            
            # 업데이트가 필요한 거래 목록을 가져옵니다
            with self.db_manager.conn.cursor() as cursor:
                if trade_id and symbol and order_id:
                    # 특정 거래만 조회
                    cursor.execute(
                        "SELECT tradeId, symbol, bybitOrderId FROM trades WHERE tradeId = %s",
                        [trade_id]
                    )
                else:
                    # FILLED 상태이고 PnL이 NULL인 모든 거래 조회
                    cursor.execute(
                        "SELECT tradeId, symbol, bybitOrderId FROM trades WHERE orderStatus = %s AND pnl IS NULL",
                        [TRADE_STATUS_FILLED]
                    )
                
                trades_to_update = cursor.fetchall()
            
            if not trades_to_update:
                logger.info("업데이트할 거래가 없습니다.")
                return
            
            # 심볼별로 거래 그룹화
            trades_by_symbol = {}
            for trade in trades_to_update:
                trade_symbol = trade["symbol"]
                if trade_symbol not in trades_by_symbol:
                    trades_by_symbol[trade_symbol] = []
                trades_by_symbol[trade_symbol].append(trade)
            
            # 각 심볼에 대해 처리
            for symbol, trades in trades_by_symbol.items():
                # 직접 API 키 가져오기
                coin_base = symbol.replace("USDT", "")  # 예: ETHUSDT -> ETH
                api_config = self.config.get_bybit_api_key(symbol)
                
                api_key = api_config.get("key", "")
                api_secret = api_config.get("secret", "")
                
                if not api_key or not api_secret:
                    logger.error(f"{symbol}에 대한 API 키가 설정되지 않았습니다.")
                    continue
                    
                logger.info(f"{symbol} API 키 사용: {api_key[:4]}...{api_key[-4:]}")
                
                # 직접 API 호출 함수
                def get_closed_pnl(symbol, order_id=None):
                    # 바이비트 API 기본 URL
                    base_url = "https://api.bybit.com"
                    
                    # 종료된 PnL API 엔드포인트
                    endpoint = "/v5/position/closed-pnl"
                    
                    # 요청 파라미터
                    params = {
                        "category": "linear",
                        "symbol": symbol,
                        "limit": 20
                    }
                    
                    # 현재 타임스탬프 (밀리초)
                    timestamp = str(int(time.time() * 1000))
                    recv_window = "5000"
                    
                    # 파라미터를 알파벳 순으로 정렬
                    sorted_params = sorted(params.items())
                    query_string = "&".join([f"{key}={value}" for key, value in sorted_params])
                    
                    # 서명 생성
                    signature_payload = f"{timestamp}{api_key}{recv_window}{query_string}"
                    signature = hmac.new(
                        api_secret.encode("utf-8"),
                        signature_payload.encode("utf-8"),
                        hashlib.sha256
                    ).hexdigest()
                    
                    # 헤더 설정
                    headers = {
                        "X-BAPI-API-KEY": api_key,
                        "X-BAPI-SIGN": signature,
                        "X-BAPI-TIMESTAMP": timestamp,
                        "X-BAPI-RECV-WINDOW": recv_window
                    }
                    
                    # API 요청 실행
                    url = f"{base_url}{endpoint}?{query_string}"
                    try:
                        logger.info(f"PnL 조회 요청: URL={url}, 헤더={headers}")
                        response = requests.get(url, headers=headers)
                        
                        if response.status_code == 200:
                            return response.json()
                        else:
                            logger.error(f"API 요청 실패: {response.status_code} - {response.text}")
                            return {"error": response.status_code, "message": response.text}
                    except Exception as e:
                        logger.error(f"API 요청 중 오류 발생: {e}")
                        return {"error": "request_failed", "message": str(e)}
                
                # 심볼에 맞는 API 키로 PnL 정보 조회
                api_response = get_closed_pnl(symbol)
                
                if "error" in api_response:
                    logger.error(f"{symbol} PnL 정보 조회 실패: {api_response}")
                    continue
                
                # 응답 확인
                if api_response.get("retCode") != 0:
                    logger.error(f"{symbol} PnL 정보 조회 실패: {api_response}")
                    continue
                
                # PnL 목록
                pnl_list = api_response.get("result", {}).get("list", [])
                
                if not pnl_list:
                    logger.warning(f"{symbol}에 대한 PnL 정보가 없습니다.")
                    continue
                
                # PnL 정보 디버깅
                logger.info(f"{symbol} PnL 목록: {pnl_list}")
                
                # 업데이트된 거래 ID를 추적하기 위한 집합
                updated_trade_ids = set()
                
                # 각 거래에 대해 매칭되는 PnL 정보를 찾아 업데이트
                for trade in trades:
                    trade_id = trade["tradeId"]
                    order_id = trade["bybitOrderId"]
                    
                    if not order_id:
                        logger.warning(f"거래 ID {trade_id}에 주문 ID가 없습니다.")
                        continue
                    
                    logger.info(f"주문 ID로 PnL 검색: {order_id}")
                    
                    # 주문 ID로 매칭되는 PnL 정보 찾기
                    matching_pnl = None
                    for pnl_item in pnl_list:
                        logger.info(f"PnL 항목: {pnl_item}")
                        if pnl_item.get("orderId") == order_id:
                            matching_pnl = pnl_item
                            logger.info(f"매칭되는 PnL 항목 발견: {matching_pnl}")
                            break
                    
                    if matching_pnl:
                        # PnL 정보 추출
                        pnl_value = float(matching_pnl.get("closedPnl", 0))
                        entry_price = float(matching_pnl.get("avgEntryPrice", 0))
                        exit_price = float(matching_pnl.get("avgExitPrice", 0))
                        
                        # DB 업데이트
                        with self.db_manager.conn.cursor() as cursor:
                            cursor.execute(
                                "UPDATE trades SET pnl = %s, additionalInfo = JSON_SET(COALESCE(additionalInfo, '{}'), '$.entry_price', %s, '$.exit_price', %s) WHERE tradeId = %s",
                                [pnl_value, entry_price, exit_price, trade_id]
                            )
                        
                        self.db_manager.conn.commit()
                        logger.info(f"거래 ID {trade_id} PnL 업데이트 완료: {pnl_value}")
                        
                        # 업데이트된 거래 ID 추가
                        updated_trade_ids.add(trade_id)
                    else:
                        logger.warning(f"거래 ID {trade_id}, 주문 ID {order_id}에 대한 매칭 PnL 정보를 찾을 수 없습니다.")
                
                # 업데이트 요약 로그
                logger.info(f"{symbol}: 총 {len(trades)}개 중 {len(updated_trade_ids)}개 거래의 PnL 정보 업데이트 완료")
                
                # API 요청 간 간격
                time.sleep(0.5)
            
        except Exception as e:
            import traceback
            logger.error(f"PnL 정보 업데이트 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

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
            trade_id = str(uuid.uuid4())
            self.db_manager.log_trade({
                "tradeId": trade_id,
                "eventId": event_id,
                "symbol": symbol,
                "orderType": "MARKET",
                "side": "Sell" if current_position["position_type"] == "long" else "Buy",
                "positionType": current_position["position_type"],
                "quantity": current_position["size"],
                "price": close_result["price"],
                "leverage": current_position["leverage"],
                "orderStatus": TRADE_STATUS_FILLED,
                "bybitOrderId": close_result.get("order_id"),
                "additionalInfo": json.dumps({"reason": "trend_touch", "ai_decision": ai_decision}),
                "executionTime": datetime.now()
            })
            
            # PnL 정보 지연 업데이트를 위한 타이머 시작
            threading.Timer(30.0, lambda: self._update_trade_pnl(trade_id, symbol, close_result.get("order_id"))).start()
            logger.info(f"PnL 정보 지연 업데이트 예약됨 (30초 후): {trade_id}")

            # 기존 거래 상태 업데이트
            try:
                # 해당 거래 상태 업데이트
                with self.db_manager.conn.cursor() as cursor:
                    cursor.execute("UPDATE trades SET orderStatus = %s WHERE symbol = %s AND positionType = %s AND orderStatus = %s", 
                                 [TRADE_STATUS_CLOSED, symbol, current_position["position_type"], TRADE_STATUS_OPEN])
                    self.db_manager.conn.commit()
            except Exception as e:
                logger.warning(f"거래 상태 업데이트 중 오류 발생: {e}")
            
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