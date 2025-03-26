-- 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS `trading_system` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `trading_system`;

-- 거래 결정 서버 테이블: decision_events
CREATE TABLE IF NOT EXISTS `decision_events` (
  `eventId` varchar(36) NOT NULL,
  `eventName` varchar(50) NOT NULL COMMENT '이벤트 유형 (open_pos, close_pos, close_trend_pos)',
  `eventSymbol` varchar(20) NOT NULL COMMENT '심볼 (BTCUSDT, ETHUSDT, SOLUSDT)',
  `eventPos` varchar(10) DEFAULT NULL COMMENT '신호 포지션 (long, short)',
  `holdingPos` varchar(10) DEFAULT 'none' COMMENT '현재 보유 포지션 (none, long, short)',
  `prAnswer` varchar(10) DEFAULT NULL COMMENT 'Claude 응답 (yes, no)',
  `prReason` text COMMENT 'Claude 응답 이유',
  `sendExecuteServer` tinyint DEFAULT '0' COMMENT '실행 서버 전송 여부 (1=전송, 0=미전송)',
  `occurKstDate` datetime NOT NULL COMMENT '발생 시간 (한국 시간)',
  `occurUtcDate` datetime NOT NULL COMMENT '발생 시간 (UTC)',
  `responseTime` float DEFAULT NULL COMMENT '응답 처리 시간 (초)',
  `entryPrice` float DEFAULT NULL COMMENT '현재 포지션 진입 가격',
  `currentPrice` float DEFAULT NULL COMMENT '현재 시장 가격',
  `additionalInfo` text COMMENT '추가 정보 (JSON)',
  `createdAt` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 생성 시간',
  PRIMARY KEY (`eventId`),
  KEY `idx_date_symbol` (`occurUtcDate`,`eventSymbol`),
  KEY `idx_event_name` (`eventName`),
  KEY `idx_symbol` (`eventSymbol`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 거래 실행 서버 테이블: trades
CREATE TABLE IF NOT EXISTS `trades` (
    `tradeId` VARCHAR(36) PRIMARY KEY,
    `eventId` VARCHAR(36) COMMENT '이벤트 ID',
    `symbol` VARCHAR(20) NOT NULL COMMENT '심볼',
    `orderType` VARCHAR(20) NOT NULL COMMENT '주문 타입 (MARKET, LIMIT)',
    `side` VARCHAR(10) NOT NULL COMMENT '주문 방향 (Buy, Sell)',
    `positionType` VARCHAR(10) NOT NULL COMMENT '포지션 타입 (long, short)',
    `quantity` DECIMAL(18,8) NOT NULL COMMENT '수량',
    `price` DECIMAL(18,8) NOT NULL COMMENT '가격',
    `leverage` INT COMMENT '레버리지',
    `takeProfit` DECIMAL(18,8) COMMENT '익절 가격',
    `stopLoss` DECIMAL(18,8) COMMENT '손절 가격',
    `orderStatus` VARCHAR(20) NOT NULL COMMENT '주문 상태 (FILLED, CANCELED, REJECTED)',
    `bybitOrderId` VARCHAR(50) COMMENT 'Bybit 주문 ID',
    `pnl` DECIMAL(18,8) COMMENT '손익',
    `additionalInfo` TEXT COMMENT '추가 정보 (JSON)',
    `executionTime` DATETIME COMMENT '실행 시간',
    `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 생성 시간',
    KEY `idx_trades_symbol` (`symbol`),
    KEY `idx_trades_eventId` (`eventId`),
    KEY `idx_trades_executionTime` (`executionTime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 거래 실행 서버용 이벤트 테이블: execution_events
CREATE TABLE IF NOT EXISTS `execution_events` (
    `eventId` VARCHAR(36) PRIMARY KEY,
    `eventType` VARCHAR(50) NOT NULL COMMENT '이벤트 유형 (OPEN_POSITION, CLOSE_POSITION, TREND_TOUCH)',
    `symbol` VARCHAR(20) NOT NULL COMMENT '심볼 (BTCUSDT, ETHUSDT, SOLUSDT)',
    `positionType` VARCHAR(10) COMMENT '포지션 타입 (long, short)',
    `execStatus` VARCHAR(20) NOT NULL COMMENT '실행 상태 (PENDING, SUCCESS, FAILED, SKIPPED, PARTIAL)',
    `requestTime` DATETIME NOT NULL COMMENT '요청 시간',
    `executionTime` DATETIME COMMENT '실행 시간',
    `executionDuration` INT COMMENT '실행 소요 시간 (ms)',
    `rawRequest` TEXT COMMENT '원본 요청 데이터 (JSON)',
    `errorMessage` TEXT COMMENT '오류 메시지',
    `requestIp` VARCHAR(50) COMMENT '요청 IP 주소',
    `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 생성 시간',
    KEY `idx_symbol` (`symbol`),
    KEY `idx_requestTime` (`requestTime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;