import hmac
import hashlib
import json
import time
import logging
import math
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Dict, Any, Optional, List, Union, Tuple

import requests


class BybitClient:
    """
    Bybit API 클라이언트
    
    Bybit V5 API와 상호작용하기 위한 클래스
    """
    BASE_URL = "https://api.bybit.com"
    
    def __init__(self, api_key: str, api_secret: str):
        """
        BybitClient 초기화
        
        Args:
            api_key: Bybit API 키
            api_secret: Bybit API 시크릿
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        
        # 로거 설정
        self.logger = logging.getLogger("bybit_client")
        self.logger.setLevel(logging.INFO)
        
        # 캐시된 심볼 정보 저장
        self.symbols_info_cache = {}
    
    def get_kline_data(self, symbol: str, interval: str, limit: int = 200) -> Dict[str, Any]:
        """
        K-line (캔들스틱) 데이터 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            interval: 시간 간격 (1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, M, W)
            limit: 조회할 캔들 수 (최대 1000)
            
        Returns:
            K-line 데이터를 포함한 응답
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        
        self.logger.info(f"{symbol} {interval}분봉 데이터 {limit}개 요청...")
        return self._send_get_request("/v5/market/kline", params)
    
    def get_order_book(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """
        오더북 데이터 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            limit: 오더북 깊이 (최대 200)
            
        Returns:
            오더북 데이터를 포함한 응답
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "limit": min(limit, 100)
        }
        
        return self._send_get_request("/v5/market/orderbook", params)
    
    def get_positions(self, symbol: str) -> Dict[str, Any]:
        """
        현재 포지션 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            포지션 정보를 포함한 응답
        """
        params = {
            "category": "linear",
            "symbol": symbol
        }
        
        response = self._send_get_request("/v5/position/list", params, True)
        
        # 포지션 정보 확인 및 처리
        if response.get("retCode") == 0:
            positions = response.get("result", {}).get("list", [])
            # 활성 상태인 포지션만 필터링
            active_positions = [pos for pos in positions if self.safe_float_conversion(pos.get("size", 0)) > 0]
            
            if active_positions:
                position = active_positions[0]
                result = {
                    "exists": True,
                    "size": self.safe_float_conversion(position.get("size", 0)),
                    "side": position.get("side"),  # Buy 또는 Sell
                    "entry_price": self.safe_float_conversion(position.get("avgPrice", 0)),
                    "leverage": self.safe_float_conversion(position.get("leverage", 1)),
                    "unrealized_pnl": self.safe_float_conversion(position.get("unrealisedPnl", 0)),
                    "take_profit": self.safe_float_conversion(position.get("takeProfit", 0)),
                    "stop_loss": self.safe_float_conversion(position.get("stopLoss", 0))
                }
                result["position_type"] = "long" if result["side"] == "Buy" else "short"
                return result
        
        # 포지션이 없거나 오류 발생 시
        return {
            "exists": False,
            "size": 0,
            "side": None,
            "position_type": None
        }
    
    def get_current_price(self, symbol: str) -> float:
        """
        현재 티커 가격 조회
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            현재 가격 (float)
        """
        params = {
            "category": "linear",
            "symbol": symbol
        }
        
        response = self._send_get_request("/v5/market/tickers", params)
        
        if response.get("retCode") == 0:
            tickers = response.get("result", {}).get("list", [])
            if tickers:
                return self.safe_float_conversion(tickers[0].get("lastPrice", 0))
        
        raise Exception(f"현재 가격 조회 실패: {response}")
    
    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """
        심볼 정보 조회 (캐싱 기능 포함)
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            심볼 정보
        """
        # 캐시된 정보가 있으면 반환
        if symbol in self.symbols_info_cache:
            return self.symbols_info_cache[symbol]
        
        params = {
            "category": "linear",
            "symbol": symbol
        }
        
        response = self._send_get_request("/v5/market/instruments-info", params)
        
        if response.get("retCode") == 0:
            instruments = response.get("result", {}).get("list", [])
            if instruments:
                instrument = instruments[0]
                
                # 필요한 정보 추출
                lot_size_filter = instrument.get("lotSizeFilter", {})
                price_filter = instrument.get("priceFilter", {})
                
                symbol_info = {
                    "min_order_qty": self.safe_float_conversion(lot_size_filter.get("minOrderQty", 0.001)),
                    "max_order_qty": self.safe_float_conversion(lot_size_filter.get("maxOrderQty", 1000000)),
                    "qty_step": self.safe_float_conversion(lot_size_filter.get("qtyStep", 0.001)),
                    "tick_size": self.safe_float_conversion(price_filter.get("tickSize", 0.01)),
                    "min_price": self.safe_float_conversion(price_filter.get("minPrice", 0)),
                    "max_price": self.safe_float_conversion(price_filter.get("maxPrice", 0)),
                    "max_leverage": int(self.safe_float_conversion(instrument.get("leverageFilter", {}).get("maxLeverage", 1)))
                }
                
                # 캐시에 저장
                self.symbols_info_cache[symbol] = symbol_info
                return symbol_info
        
        raise Exception(f"심볼 정보 조회 실패: {response}")
    
    def place_market_order(self, symbol: str, side: str, qty: str, reduce_only: bool = False) -> Dict[str, Any]:
        """
        시장가 주문 실행
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            side: 주문 방향 (Buy/Sell)
            qty: 주문 수량
            reduce_only: 포지션 감소 전용 여부
            
        Returns:
            주문 결과
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty,
            "reduceOnly": reduce_only
        }
        
        return self._send_post_request("/v5/order/create", params)
    
    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        레버리지 설정
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            leverage: 레버리지 배수
            
        Returns:
            설정 결과
        """
        # 심볼 정보 확인
        symbol_info = self.get_symbol_info(symbol)
        max_leverage = symbol_info.get("max_leverage", 1)
        
        # 최대 레버리지 제한
        if int(leverage) > max_leverage:
            self.logger.warning(f"요청한 레버리지({leverage})가 최대 레버리지({max_leverage})를 초과하여 제한됩니다.")
            leverage = max_leverage
        
        params = {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage)
        }
        
        return self._send_post_request("/v5/position/set-leverage", params)
    
    def close_position(self, symbol: str) -> bool:
        """
        포지션 청산
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            성공 여부
        """
        # 현재 포지션 조회
        position = self.get_positions(symbol)
        
        if not position.get("exists", False):
            self.logger.info(f"{symbol} 포지션이 없습니다.")
            return True
        
        # 포지션 방향의 반대 방향으로 시장가 주문
        side = "Sell" if position.get("side") == "Buy" else "Buy"
        qty = str(position.get("size"))
        
        try:
            result = self.place_market_order(
                symbol=symbol,
                side=side,
                qty=qty,
                reduce_only=True
            )
            
            if result.get("retCode") == 0:
                self.logger.info(f"{symbol} 포지션 청산 성공")
                return True
            else:
                self.logger.error(f"{symbol} 포지션 청산 실패: {result}")
                return False
        except Exception as e:
            self.logger.error(f"{symbol} 포지션 청산 중 오류 발생: {e}")
            return False
    
    def cancel_all_orders(self, symbol: str) -> bool:
        """
        모든 주문 취소
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            
        Returns:
            성공 여부
        """
        params = {
            "category": "linear",
            "symbol": symbol
        }
        
        try:
            result = self._send_post_request("/v5/order/cancel-all", params)
            
            if result.get("retCode") == 0:
                self.logger.info(f"{symbol} 모든 주문 취소 성공")
                return True
            else:
                self.logger.error(f"{symbol} 모든 주문 취소 실패: {result}")
                return False
        except Exception as e:
            self.logger.error(f"{symbol} 주문 취소 중 오류 발생: {e}")
            return False
    
    def set_tp_sl(self, symbol: str, tp_price: float, sl_price: float) -> bool:
        """
        TP/SL 설정
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            tp_price: 익절 가격
            sl_price: 손절 가격
            
        Returns:
            성공 여부
        """
        # 현재 포지션 조회
        position = self.get_positions(symbol)
        
        if not position.get("exists", False):
            self.logger.warning(f"{symbol} 포지션이 없어 TP/SL을 설정할 수 없습니다.")
            return False
        
        # 가격 소수점 자릿수 계산
        symbol_info = self.get_symbol_info(symbol)
        tick_size = symbol_info.get("tick_size")
        
        # 소수점 자릿수 계산
        decimal_places = self._get_decimal_places(tick_size)
        
        # 가격 반올림
        tp_price = self._round_to_tick(tp_price, tick_size, decimal_places)
        sl_price = self._round_to_tick(sl_price, tick_size, decimal_places)
        
        params = {
            "category": "linear",
            "symbol": symbol,
            "takeProfit": str(tp_price),
            "stopLoss": str(sl_price),
            "positionIdx": 0,  # 단일 포지션 모드
            "tpTriggerBy": "LastPrice",
            "slTriggerBy": "LastPrice",
            "tpslMode": "Full"  # Full: 전체 포지션에 적용
        }
        
        try:
            result = self._send_post_request("/v5/position/trading-stop", params)
            
            if result.get("retCode") == 0:
                self.logger.info(f"{symbol} TP({tp_price})/SL({sl_price}) 설정 성공")
                return True
            else:
                self.logger.error(f"{symbol} TP/SL 설정 실패: {result}")
                return False
        except Exception as e:
            self.logger.error(f"{symbol} TP/SL 설정 중 오류 발생: {e}")
            return False
    
    def get_account_balance(self, coin: str = "USDT") -> Dict[str, float]:
        """
        계좌 잔고 조회
        
        Args:
            coin: 화폐 단위 (예: "USDT")
            
        Returns:
            잔고 정보
        """
        params = {
            "accountType": "UNIFIED",
            "coin": coin
        }
        
        response = self._send_get_request("/v5/account/wallet-balance", params, True)
        
        if response.get("retCode") == 0:
            account_list = response.get("result", {}).get("list", [])
            if account_list:
                coins = account_list[0].get("coin", [])
                for coin_data in coins:
                    if coin_data.get("coin") == coin:
                        return {
                            "total": self.safe_float_conversion(coin_data.get("walletBalance", 0)),
                            "available": self.safe_float_conversion(coin_data.get("availableToWithdraw", 0)),
                            "margin_balance": self.safe_float_conversion(coin_data.get("totalMarginBalance", 0))
                        }
        
        raise Exception(f"계좌 잔고 조회 실패: {response}")
    
    def calculate_order_quantity(self, symbol: str, position_size_mode: str, position_size_value: float, leverage: int, current_price: float) -> float:
        """
        주문 수량 계산
        
        Args:
            symbol: 심볼 (예: "BTCUSDT")
            position_size_mode: 포지션 크기 모드 ("fixed" 또는 "percent")
            position_size_value: 포지션 크기 값 (fixed: USDT 금액, percent: 백분율)
            leverage: 레버리지
            current_price: 현재 가격
            
        Returns:
            계산된 주문 수량
        """
        try:
            # 심볼 정보 조회
            symbol_info = self.get_symbol_info(symbol)
            
            # 심볼 정보에서 필요한 값 추출
            min_qty = Decimal(str(symbol_info.get("min_order_qty", 0.001)))
            step_size = Decimal(str(symbol_info.get("qty_step", 0.001)))
            max_order_qty = Decimal(str(symbol_info.get("max_order_qty", float("inf"))))
            
            # 마진 계산 (고정 금액 또는 계정 잔고의 비율)
            if position_size_mode == "fixed":
                # 고정 금액 모드
                notional = Decimal(str(position_size_value)) * Decimal(str(leverage))
            else:
                # 계좌 비율 모드
                balance = self.get_account_balance()
                total_balance = Decimal(str(balance["total"]))
                margin = total_balance * (Decimal(str(position_size_value)) / Decimal("100.0"))
                notional = margin * Decimal(str(leverage))
            
            # 가격으로 나누어 수량 계산
            raw_qty = notional / Decimal(str(current_price))
            
            # step_size에 맞게 수량 조정 (내림)
            steps = (raw_qty / step_size).to_integral_value(rounding=ROUND_DOWN)
            qty = steps * step_size
            
            # 최소 주문 수량 확인
            if qty < min_qty:
                # 최소 주문 수량으로 조정 (step_size의 배수가 되도록)
                steps = (min_qty / step_size).to_integral_value(rounding=ROUND_UP)
                qty = steps * step_size
            
            # 최대 주문 수량 확인
            if qty > max_order_qty:
                qty = max_order_qty
            
            # 로그 추가
            self.logger.info(f"주문 수량 계산: 모드={position_size_mode}, 값={position_size_value}, 레버리지={leverage}, 계산된 수량={float(qty)}")
            
            return float(qty)
        except Exception as e:
            self.logger.error(f"주문 수량 계산 중 오류 발생: {e}")
            raise
    
    def _send_get_request(self, endpoint: str, params: Dict[str, Any], requires_auth: bool = False) -> Dict[str, Any]:
        """
        Bybit API에 GET 요청 전송
        
        Args:
            endpoint: API 엔드포인트
            params: 쿼리 파라미터
            requires_auth: 인증이 필요한지 여부
            
        Returns:
            API 응답
        """
        url = self.BASE_URL + endpoint
        
        # 인증이 필요한 경우 헤더 추가
        headers = {}
        if requires_auth:
            timestamp = int(time.time() * 1000)
            recv_window = "5000"
            
            # 쿼리 문자열 생성
            query_string = "&".join([f"{key}={params[key]}" for key in sorted(params.keys())])
            
            # 서명 생성
            sign_string = f"{timestamp}{self.api_key}{recv_window}{query_string}"
            signature = hmac.new(
                self.api_secret.encode(),
                sign_string.encode(),
                hashlib.sha256
            ).hexdigest()
            
            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": str(timestamp),
                "X-BAPI-RECV-WINDOW": recv_window,
                "X-BAPI-SIGN": signature
            }
        
        # 최대 3번 재시도
        max_retries = 3
        for retry in range(max_retries):
            try:
                # 요청 전송
                response = self.session.get(url, params=params, headers=headers)
                
                # 응답 확인
                if response.status_code != 200:
                    if retry < max_retries - 1:
                        self.logger.warning(f"API 요청 실패 (재시도 {retry+1}/{max_retries}): {response.status_code} - {response.text}")
                        time.sleep(1)  # 재시도 전 대기
                        continue
                    raise Exception(f"API 요청 실패: {response.status_code} - {response.text}")
                
                return response.json()
            except Exception as e:
                if retry < max_retries - 1:
                    self.logger.warning(f"API 요청 중 오류 발생 (재시도 {retry+1}/{max_retries}): {e}")
                    time.sleep(1)  # 재시도 전 대기
                    continue
                raise
        
        # 모든 재시도 실패 시
        raise Exception("API 요청 실패: 최대 재시도 횟수 초과")
    
    def _send_post_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bybit API에 POST 요청 전송
        
        Args:
            endpoint: API 엔드포인트
            params: 요청 파라미터
            
        Returns:
            API 응답
        """
        url = self.BASE_URL + endpoint
        timestamp = int(time.time() * 1000)
        recv_window = "5000"
        
        # JSON으로 변환
        json_params = json.dumps(params)
        
        # 서명 생성
        sign_string = f"{timestamp}{self.api_key}{recv_window}{json_params}"
        signature = hmac.new(
            self.api_secret.encode(),
            sign_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # 헤더 설정
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": recv_window,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json"
        }
        
        # 최대 3번 재시도
        max_retries = 3
        for retry in range(max_retries):
            try:
                # 요청 전송
                response = self.session.post(url, data=json_params, headers=headers)
                
                # 응답 확인
                if response.status_code != 200:
                    if retry < max_retries - 1:
                        self.logger.warning(f"API 요청 실패 (재시도 {retry+1}/{max_retries}): {response.status_code} - {response.text}")
                        time.sleep(1)  # 재시도 전 대기
                        continue
                    raise Exception(f"API 요청 실패: {response.status_code} - {response.text}")
                
                return response.json()
            except Exception as e:
                if retry < max_retries - 1:
                    self.logger.warning(f"API 요청 중 오류 발생 (재시도 {retry+1}/{max_retries}): {e}")
                    time.sleep(1)  # 재시도 전 대기
                    continue
                raise
        
        # 모든 재시도 실패 시
        raise Exception("API 요청 실패: 최대 재시도 횟수 초과")
    
    @staticmethod
    def _get_decimal_places(step_size: float) -> int:
        """
        소수점 자릿수 계산
        
        Args:
            step_size: 스텝 사이즈
            
        Returns:
            소수점 자릿수
        """
        step_str = str(step_size).rstrip('0').rstrip('.') if '.' in str(step_size) else str(step_size)
        if '.' in step_str:
            return len(step_str.split('.')[1])
        return 0
    
    @staticmethod
    def _round_to_tick(price: float, tick_size: float, decimal_places: int) -> float:
        """
        가격을 tick_size에 맞게 반올림
        
        Args:
            price: 가격
            tick_size: 틱 사이즈
            decimal_places: 소수점 자릿수
            
        Returns:
            반올림된 가격
        """
        return round(math.floor(price / tick_size) * tick_size, decimal_places)
    
    @staticmethod
    def safe_float_conversion(value: Optional[Union[str, int, float]]) -> float:
        """
        값을 안전하게 float로 변환
        
        Args:
            value: 변환할 값 (문자열, 정수, 실수 또는 None)
            
        Returns:
            변환된 float 값 또는 변환 실패 시 0.0
        """
        if value is None or value == "":
            return 0.0
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
