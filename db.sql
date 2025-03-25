-- 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS `trading_decisions` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `trading_decisions`;

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
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_eventId ON trades(eventId);
CREATE INDEX idx_trades_executionTime ON trades(executionTime);