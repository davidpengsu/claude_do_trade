import logging
import pymysql
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

class ExecDBManager:
    """
    실행 데이터베이스 관리자
    
    실행 이벤트 및 거래 로그를 데이터베이스에 기록
    """
    
    def __init__(self, host: str, user: str, password: str, database: str, port: int = 3306):
        """
        ExecDBManager 초기화
        
        Args:
            host: 데이터베이스 호스트
            user: 데이터베이스 사용자
            password: 데이터베이스 비밀번호
            database: 데이터베이스 이름
            port: MySQL 포트 (기본값: 3306)
        """
        self.config = {
            'host': host,
            'user': user,
            'password': password,
            'database': database,
            'port': port,
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }
        self.logger = logging.getLogger("exec_db_manager")
        self._init_connection()
    
    def _init_connection(self):
        """데이터베이스 연결 초기화"""
        try:
            self.conn = pymysql.connect(**self.config)
            self.logger.info("데이터베이스 연결 성공")
        except pymysql.Error as e:
            self.logger.error(f"데이터베이스 연결 오류: {e}")
            raise
    
    def _ensure_connection(self):
        """데이터베이스 연결 유효성 확인"""
        try:
            self.conn.ping(reconnect=True)
        except pymysql.Error:
            self.logger.warning("데이터베이스 연결이 끊어짐, 재연결 시도...")
            self._init_connection()
    
    def log_execution_event(self, event_data: Dict[str, Any]) -> bool:
        """
        실행 이벤트를 데이터베이스에 기록
        
        Args:
            event_data: 기록할 이벤트 데이터
            
        Returns:
            성공 여부
        """
        self._ensure_connection()
        
        try:
            # 복잡한 객체를 JSON 문자열로 변환
            for key, value in event_data.items():
                if isinstance(value, (dict, list)):
                    event_data[key] = json.dumps(value)
            
            # 사용 가능한 필드를 기반으로 쿼리 동적 구성
            fields = ", ".join(event_data.keys())
            placeholders = ", ".join(["%s"] * len(event_data))
            values = list(event_data.values())
            
            query = f"INSERT INTO execution_events ({fields}) VALUES ({placeholders})"
            
            with self.conn.cursor() as cursor:
                cursor.execute(query, values)
            self.conn.commit()
            
            self.logger.info(f"실행 이벤트 기록 완료: {event_data.get('eventId', 'unknown')}")
            return True
            
        except Exception as e:
            self.logger.error(f"실행 이벤트 기록 중 오류 발생: {e}")
            self.conn.rollback()
            return False
    
    def update_execution_event(self, event_id: str, update_data: Dict[str, Any]) -> bool:
        """
        실행 이벤트 업데이트
        
        Args:
            event_id: 이벤트 ID
            update_data: 업데이트할 데이터
            
        Returns:
            성공 여부
        """
        self._ensure_connection()
        
        try:
            # 복잡한 객체를 JSON 문자열로 변환
            for key, value in update_data.items():
                if isinstance(value, (dict, list)):
                    update_data[key] = json.dumps(value)
            
            # 업데이트 쿼리 구성
            set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
            values = list(update_data.values())
            values.append(event_id)
            
            query = f"UPDATE execution_events SET {set_clause} WHERE eventId = %s"
            
            with self.conn.cursor() as cursor:
                cursor.execute(query, values)
            self.conn.commit()
            
            self.logger.info(f"실행 이벤트 업데이트 완료: {event_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"실행 이벤트 업데이트 중 오류 발생: {e}")
            self.conn.rollback()
            return False
    
    def log_trade(self, trade_data: Dict[str, Any]) -> bool:
        """
        거래 정보 기록
        
        Args:
            trade_data: 기록할 거래 데이터
            
        Returns:
            성공 여부
        """
        self._ensure_connection()
        
        try:
            # 복잡한 객체를 JSON 문자열로 변환
            for key, value in trade_data.items():
                if isinstance(value, (dict, list)):
                    trade_data[key] = json.dumps(value)
            
            # 사용 가능한 필드를 기반으로 쿼리 동적 구성
            fields = ", ".join(trade_data.keys())
            placeholders = ", ".join(["%s"] * len(trade_data))
            values = list(trade_data.values())
            
            query = f"INSERT INTO trades ({fields}) VALUES ({placeholders})"
            
            with self.conn.cursor() as cursor:
                cursor.execute(query, values)
            self.conn.commit()
            
            self.logger.info(f"거래 기록 완료: {trade_data.get('tradeId', 'unknown')}")
            return True
            
        except Exception as e:
            self.logger.error(f"거래 기록 중 오류 발생: {e}")
            self.conn.rollback()
            return False
    
        
    def get_opened_trades(self) -> List[tuple]:
        """
        진행 중인 거래 목록 조회
        
        Returns:
            미완료 거래 ID 목록
        """
        self._ensure_connection()
        
        try:
            with self.conn.cursor() as cursor:
                # 필드명과 상태값 수정
                cursor.execute("SELECT bybitOrderId FROM trades WHERE orderStatus = 'OPEN'")
                return [(row['bybitOrderId'],) for row in cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"미완료 거래 조회 중 오류 발생: {e}")
            return []
    
    def close(self):
        """데이터베이스 연결 종료"""
        try:
            if hasattr(self, 'conn'):
                self.conn.close()
                self.logger.info("데이터베이스 연결 종료")
        except Exception as e:
            self.logger.error(f"데이터베이스 연결 종료 중 오류 발생: {e}")
