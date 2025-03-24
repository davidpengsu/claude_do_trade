import json
import os
import logging
from typing import Dict, Any, List, Optional

class ConfigLoader:
    """
    설정 파일 로드 유틸리티 클래스
    """
    
    def __init__(self, config_dir: str = "config"):
        """
        ConfigLoader 초기화
        
        Args:
            config_dir: 설정 파일 디렉토리 경로
        """
        self.config_dir = config_dir
        self.logger = logging.getLogger("config_loader")
        
        # 설정 디렉토리가 없으면 생성
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
    
    def load_config(self, filename: str) -> Dict[str, Any]:
        """
        설정 파일 로드
        
        Args:
            filename: 설정 파일 이름
            
        Returns:
            설정 파일 내용
        """
        path = os.path.join(self.config_dir, filename)
        return self._load_json(path)
    
    def save_config(self, filename: str, data: Dict[str, Any]) -> bool:
        """
        설정 파일 저장
        
        Args:
            filename: 설정 파일 이름
            data: 저장할 데이터
            
        Returns:
            성공 여부
        """
        path = os.path.join(self.config_dir, filename)
        return self._save_json(path, data)
    
    def get_bybit_api_key(self, symbol: str) -> Dict[str, str]:
        """
        특정 코인의 Bybit API 키 조회
        
        Args:
            symbol: 코인 심볼 (BTC, ETH, SOL 등)
            
        Returns:
            API 키 및 시크릿
        """
        api_keys = self.load_config("api_keys.json")
        
        # 코인 심볼에서 USDT 부분 제거 (예: BTCUSDT -> BTC)
        coin_base = symbol.replace("USDT", "")
        
        # 해당 코인의 API 키 조회
        coin_api = api_keys.get("bybit_api", {}).get(coin_base, {})
        
        # API 키가 없으면 빈 딕셔너리 반환
        if not coin_api:
            self.logger.warning(f"{coin_base}에 대한 API 키가 설정되지 않았습니다.")
            return {"key": "", "secret": ""}
        
        return coin_api
    
    def get_db_config(self) -> Dict[str, Any]:
        """
        데이터베이스 설정 조회
        
        Returns:
            데이터베이스 접속 정보
        """
        db_config = self.load_config("db_config.json")
        
        # 설정이 없으면 기본값 반환
        if not db_config:
            self.logger.warning("데이터베이스 설정이 없습니다. 기본 설정 사용.")
            return {
                "host": "localhost",
                "user": "root",
                "password": "",
                "database": "execution_data"
            }
        
        return db_config
    
    def get_supported_symbols(self) -> List[str]:
        """
        지원하는 코인 심볼 목록 조회
        
        Returns:
            지원하는 코인 심볼 리스트
        """
        api_keys = self.load_config("api_keys.json")
        symbols = []
        
        bybit_api = api_keys.get("bybit_api", {})
        for symbol in bybit_api:
            if symbol not in ["key", "secret"]:  # 일반 API 키 항목 제외
                symbols.append(f"{symbol}USDT")
        
        return symbols
    
    def _load_json(self, filepath: str) -> Dict[str, Any]:
        """
        JSON 파일 로드
        
        Args:
            filepath: 파일 경로
            
        Returns:
            JSON 내용
        """
        try:
            if not os.path.exists(filepath):
                return {}
                
            with open(filepath, 'r', encoding='utf-8') as file:
                return json.load(file)
                
        except Exception as e:
            self.logger.error(f"{filepath} 로드 중 오류 발생: {e}")
            return {}
    
    def _save_json(self, filepath: str, data: Dict[str, Any]) -> bool:
        """
        JSON 파일 저장
        
        Args:
            filepath: 파일 경로
            data: 저장할 데이터
            
        Returns:
            성공 여부
        """
        try:
            with open(filepath, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            return True
            
        except Exception as e:
            self.logger.error(f"{filepath} 저장 중 오류 발생: {e}")
            return False
    
    def create_default_configs(self) -> None:
        """기본 설정 파일 생성"""
        # API 키 설정
        api_keys = {
            "bybit_api": {
                "BTC": {
                    "key": "your-btc-api-key",
                    "secret": "your-btc-api-secret"
                },
                "ETH": {
                    "key": "your-eth-api-key",
                    "secret": "your-eth-api-secret"
                },
                "SOL": {
                    "key": "your-sol-api-key",
                    "secret": "your-sol-api-secret"
                }
            }
        }
        self.save_config("api_keys.json", api_keys)
        
        # 거래 설정
        trade_settings = {
            "position_size_mode": "percent",  # "percent" 또는 "fixed"
            "position_size_percent": 10.0,    # 기본적으로 계좌 잔고의 10% 사용
            "position_size_fixed": 100.0,     # 고정 금액 (USDT)
            "leverage": 5,                    # 기본 레버리지 5배
            "tp_percent": 3.0,                # 3% 익절
            "sl_percent": 1.5,                # 1.5% 손절
            "require_api_key": True,          # API 키 요구 여부
            "api_key": "your-execution-server-api-key"  # 실행 서버 API 키
        }
        self.save_config("trade_settings.json", trade_settings)
        
        # 데이터베이스 설정
        db_config = {
            "host": "localhost",
            "user": "root",
            "password": "",
            "database": "execution_data",
            "port": 3306
        }
        self.save_config("db_config.json", db_config)
