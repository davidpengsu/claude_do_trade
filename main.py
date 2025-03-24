import os
import sys
import logging
import argparse
import signal
import time
from threading import Thread

from exec_server import start_server
from exec_manager import ExecManager
from config_loader import ConfigLoader

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)
os.makedirs("config", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/main.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("main")

# 전역 변수
running = True
server_thread = None
exec_manager = None

def signal_handler(sig, frame):
    """시그널 핸들러 (Ctrl+C 등)"""
    global running
    logger.info("종료 신호 수신. 서버를 종료합니다...")
    running = False
    sys.exit(0)

def initialize_environment():
    """환경 초기화 및 기본 설정 확인"""
    try:
        # 설정 로더 생성
        config = ConfigLoader()
        
        # 설정 파일 확인 및 생성
        trade_settings = config.load_config("trade_settings.json")
        api_keys = config.load_config("api_keys.json")
        db_config = config.load_config("db_config.json")
        
        # 설정 파일이 없으면 기본 설정 생성
        if not trade_settings or not api_keys or not db_config:
            logger.info("기본 설정 파일이 없습니다. 기본 설정 파일을 생성합니다.")
            config.create_default_configs()
            logger.info("config/ 디렉토리에 기본 설정 파일이 생성되었습니다. 설정을 확인하고 서버를 다시 시작하세요.")
            return False
        
        # API 키 확인
        for coin in ["BTC", "ETH", "SOL"]:
            coin_api = api_keys.get("bybit_api", {}).get(coin, {})
            if not coin_api or not coin_api.get("key") or not coin_api.get("secret"):
                logger.warning(f"{coin} API 키가 설정되지 않았습니다. config/api_keys.json 파일을 확인하세요.")
        
        return True
    
    except Exception as e:
        logger.exception(f"환경 초기화 중 오류 발생: {e}")
        return False

def create_db_init_script():
    """데이터베이스 초기화 스크립트 생성"""
    try:
        script_path = "db_init.sql"
        
        with open(script_path, 'w') as f:
            f.write("""-- 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS execution_data;
USE execution_data;

-- 실행 이벤트 테이블
CREATE TABLE IF NOT EXISTS execution_events (
    eventId VARCHAR(36) PRIMARY KEY,
    eventType VARCHAR(50) NOT NULL COMMENT '이벤트 유형 (OPEN_POSITION, CLOSE_POSITION, TREND_TOUCH)',
    symbol VARCHAR(20) NOT NULL COMMENT '심볼 (BTCUSDT, ETHUSDT, SOLUSDT)',
    positionType VARCHAR(10) COMMENT '포지션 타입 (long, short)',
    execStatus VARCHAR(20) NOT NULL COMMENT '실행 상태 (PENDING, SUCCESS, FAILED, SKIPPED, PARTIAL)',
    requestTime DATETIME NOT NULL COMMENT '요청 시간',
    executionTime DATETIME COMMENT '실행 시간',
    executionDuration INT COMMENT '실행 소요 시간 (ms)',
    rawRequest TEXT COMMENT '원본 요청 데이터 (JSON)',
    errorMessage TEXT COMMENT '오류 메시지',
    requestIp VARCHAR(50) COMMENT '요청 IP 주소',
    createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 생성 시간'
);

-- 거래 테이블
CREATE TABLE IF NOT EXISTS trades (
    tradeId VARCHAR(36) PRIMARY KEY,
    eventId VARCHAR(36) COMMENT '이벤트 ID',
    symbol VARCHAR(20) NOT NULL COMMENT '심볼',
    orderType VARCHAR(20) NOT NULL COMMENT '주문 타입 (MARKET, LIMIT)',
    side VARCHAR(10) NOT NULL COMMENT '주문 방향 (Buy, Sell)',
    positionType VARCHAR(10) NOT NULL COMMENT '포지션 타입 (long, short)',
    quantity DECIMAL(18,8) NOT NULL COMMENT '수량',
    price DECIMAL(18,8) NOT NULL COMMENT '가격',
    leverage INT COMMENT '레버리지',
    takeProfit DECIMAL(18,8) COMMENT '익절 가격',
    stopLoss DECIMAL(18,8) COMMENT '손절 가격',
    orderStatus VARCHAR(20) NOT NULL COMMENT '주문 상태 (FILLED, CANCELED, REJECTED)',
    bybitOrderId VARCHAR(50) COMMENT 'Bybit 주문 ID',
    pnl DECIMAL(18,8) COMMENT '손익',
    additionalInfo TEXT COMMENT '추가 정보 (JSON)',
    executionTime DATETIME COMMENT '실행 시간',
    createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 생성 시간'
);

-- 인덱스 생성
CREATE INDEX idx_symbol ON execution_events(symbol);
CREATE INDEX idx_requestTime ON execution_events(requestTime);
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_eventId ON trades(eventId);
CREATE INDEX idx_trades_executionTime ON trades(executionTime);

-- 권한 설정 (필요시 주석 해제 및 수정)
-- CREATE USER IF NOT EXISTS 'execution_user'@'localhost' IDENTIFIED BY 'your_password';
-- GRANT ALL PRIVILEGES ON execution_data.* TO 'execution_user'@'localhost';
-- FLUSH PRIVILEGES;
""")
        
        logger.info(f"데이터베이스 초기화 스크립트가 {script_path}에 생성되었습니다.")
        logger.info("이 스크립트를 MySQL 서버에서 실행하여 데이터베이스를 초기화하세요.")
        logger.info("예: mysql -u root -p < db_init.sql")
        
    except Exception as e:
        logger.error(f"DB 초기화 스크립트 생성 중 오류 발생: {e}")

def parse_arguments():
    """명령행 인자 파싱"""
    parser = argparse.ArgumentParser(description='거래 실행 서버')
    parser.add_argument('--port', type=int, default=8001, help='실행 서버 포트 번호 (기본값: 8001)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='실행 서버 호스트 (기본값: 0.0.0.0)')
    parser.add_argument('--init', action='store_true', help='기본 설정 파일 생성 후 종료')
    parser.add_argument('--init-db', action='store_true', help='데이터베이스 초기화 스크립트 생성 후 종료')
    return parser.parse_args()

def show_status():
    """시스템 상태 요약 출력"""
    config = ConfigLoader()
    trade_settings = config.load_config("trade_settings.json")
    db_config = config.load_config("db_config.json")
    
    logger.info("=" * 50)
    logger.info("거래 실행 서버 시작")
    logger.info("=" * 50)
    logger.info(f"포트: {args.port}")
    logger.info(f"호스트: {args.host}")
    logger.info(f"레버리지: {trade_settings.get('leverage', 5)}x")
    logger.info(f"포지션 크기: {trade_settings.get('position_size_mode', 'percent')} "
               f"({trade_settings.get('position_size_percent', 10.0) if trade_settings.get('position_size_mode') == 'percent' else trade_settings.get('position_size_fixed', 100.0)})")
    logger.info(f"익절: {trade_settings.get('tp_percent', 3.0)}%")
    logger.info(f"손절: {trade_settings.get('sl_percent', 1.5)}%")
    logger.info(f"API 키 요구: {trade_settings.get('require_api_key', True)}")
    logger.info(f"DB 호스트: {db_config.get('host', 'localhost')}")
    logger.info("=" * 50)
    logger.info("엔드포인트:")
    logger.info(f"- 실행 엔드포인트: http://{args.host}:{args.port}/execute")
    logger.info(f"- 상태 확인: http://{args.host}:{args.port}/health")
    logger.info(f"- 포지션 조회: http://{args.host}:{args.port}/positions")
    logger.info("=" * 50)

if __name__ == "__main__":
    # 인자 파싱
    args = parse_arguments()
    
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 초기화 모드 처리
    if args.init:
        config = ConfigLoader()
        config.create_default_configs()
        logger.info("기본 설정 파일이 생성되었습니다. 설정을 확인하고 서버를 다시 시작하세요.")
        sys.exit(0)
    
    # DB 초기화 스크립트 생성 모드 처리
    if args.init_db:
        create_db_init_script()
        sys.exit(0)
    
    # 환경 초기화
    if not initialize_environment():
        logger.error("환경 초기화에 실패했습니다. 서버를 종료합니다.")
        sys.exit(1)
    
    # 시스템 상태 출력
    show_status()
    
    # 서버 스레드 시작
    server_thread = Thread(target=start_server, args=(args.host, args.port))
    server_thread.daemon = True
    server_thread.start()
    
    # 메인 스레드 유지
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("사용자에 의해 종료됩니다...")
    finally:
        logger.info("서버 종료")
