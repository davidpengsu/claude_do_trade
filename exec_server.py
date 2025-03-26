import json
import logging
import os
import traceback
from datetime import datetime
from flask import Flask, request, jsonify
from typing import Dict, Any

from exec_manager import ExecManager
from config_loader import ConfigLoader

# 로그 디렉토리 생성
os.makedirs("logs", exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/exec_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("exec_server")

# 설정 로드
config = ConfigLoader()
trade_settings = config.load_config("trade_settings.json")

# Flask 앱 생성
app = Flask(__name__)

# 실행 관리자 초기화
exec_manager = ExecManager()

@app.route('/execute', methods=['POST'])
def execute():
    """
    거래 실행 엔드포인트
    
    결정 서버로부터 거래 실행 요청을 받아 처리합니다.
    
    요청 형식:
    {
      "action": "open_position",  // "open_position", "close_position", "trend_touch"
      "symbol": "BTCUSDT",
      "position_type": "long",    // "long" 또는 "short" (open_position에만 필요)
      "ai_decision": {            // AI 결정 정보 (trend_touch에서 사용)
        "Answer": "yes",
        "Reason": "상승 추세가 예상됨"
      }
    }
    """
    start_time = datetime.now()
    
    # 요청 검증
    if not request.is_json:
        logger.error("JSON 형식이 아닌 요청 수신")
        return jsonify({"status": "error", "message": "JSON 형식으로 요청해주세요"}), 400
    
    # 클라이언트 IP 확인
    client_ip = request.remote_addr
    
    # API 키 검증 (설정에서 요구하는 경우)
    api_key = request.headers.get('X-API-Key')
    if trade_settings.get("require_api_key", False):
        expected_api_key = trade_settings.get("api_key", "")
        if not api_key or api_key != expected_api_key:
            logger.warning(f"유효하지 않은 API 키: {client_ip}")
            return jsonify({"status": "error", "message": "유효하지 않은 API 키"}), 401
    
    # 요청 처리
    try:
        request_data = request.json
        logger.info(f"실행 요청 수신: {json.dumps(request_data)}")
        
        # 필수 필드 유효성 검사
        required_fields = ["action", "symbol"]
        if not all(field in request_data for field in required_fields):
            logger.error("필수 필드 누락")
            return jsonify({
                "status": "error", 
                "message": f"필수 필드 누락. 필요한 필드: {', '.join(required_fields)}"
            }), 400
        
        # 액션별 필수 필드 검사
        action = request_data.get("action")
        
        # open_position 액션인 경우 position_type 필드 필요
        if action == "open_position" and "position_type" not in request_data:
            logger.error("open_position 액션에는 position_type이 필요합니다")
            return jsonify({
                "status": "error", 
                "message": "open_position 액션에는 position_type이 필요합니다"
            }), 400
        
        # trend_touch 액션인 경우 ai_decision 필드 필요
        if action == "trend_touch" and "ai_decision" not in request_data:
            logger.error("trend_touch 액션에는 ai_decision이 필요합니다")
            return jsonify({
                "status": "error", 
                "message": "trend_touch 액션에는 ai_decision이 필요합니다"
            }), 400
        
        # 심볼 형식 검증 (USDT 페어 확인)
        symbol = request_data.get("symbol", "")
        if not symbol.endswith("USDT"):
            logger.warning(f"지원되지 않는 심볼 형식: {symbol}")
            return jsonify({
                "status": "error", 
                "message": "USDT 페어만 지원됩니다 (예: BTCUSDT)"
            }), 400
        
        # 실행 요청 처리
        result = exec_manager.handle_execution_request(request_data, client_ip)
        
        # 응답 반환
        execution_time = (datetime.now() - start_time).total_seconds()
        result["execution_time"] = f"{execution_time:.3f}초"
        
        return jsonify(result)
        
    except Exception as e:
        logger.exception(f"실행 요청 처리 중 오류 발생: {e}")
        error_trace = traceback.format_exc()
        return jsonify({
            "status": "error",
            "message": f"서버 오류: {str(e)}",
            "execution_time": f"{(datetime.now() - start_time).total_seconds():.3f}초",
            "error_trace": error_trace
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """
    상태 확인 엔드포인트
    
    서버 상태와 지원되는 심볼 목록을 반환합니다.
    """
    try:
        supported_symbols = config.get_supported_symbols()
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "service": "execution_server",
            "supported_symbols": supported_symbols,
            "api_key_required": trade_settings.get("require_api_key", True)
        })
    except Exception as e:
        logger.exception(f"상태 확인 중 오류 발생: {e}")
        return jsonify({
            "status": "error",
            "message": f"상태 확인 중 오류 발생: {str(e)}"
        }), 500

@app.route('/positions', methods=['GET'])
def positions():
    """
    현재 포지션 조회 엔드포인트
    
    모든 지원되는 심볼에 대한 현재 포지션 정보를 반환합니다.
    """
    try:
        # API 키 검증
        api_key = request.headers.get('X-API-Key')
        if trade_settings.get("require_api_key", False):
            expected_api_key = trade_settings.get("api_key", "")
            if not api_key or api_key != expected_api_key:
                logger.warning(f"유효하지 않은 API 키: {request.remote_addr}")
                return jsonify({"status": "error", "message": "유효하지 않은 API 키"}), 401
        
        result = {}
        positions_count = 0
        
        for symbol, trader in exec_manager.traders.items():
            position = trader.get_current_position()
            if position:
                result[symbol] = position
                positions_count += 1
        
        return jsonify({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "positions": result,
            "count": positions_count
        })
        
    except Exception as e:
        logger.exception(f"포지션 조회 중 오류 발생: {e}")
        return jsonify({
            "status": "error",
            "message": f"포지션 조회 중 오류 발생: {str(e)}"
        }), 500
    
@app.route('/update-pnl', methods=['POST'])
def update_pnl():
    """
    PnL 정보 업데이트 엔드포인트
    FILLED 상태이지만 PnL이 NULL인 거래들을 찾아서 업데이트
    """
    try:
        # API 키 검증
        api_key = request.headers.get('X-API-Key')
        if trade_settings.get("require_api_key", False):
            expected_api_key = trade_settings.get("api_key", "")
            if not api_key or api_key != expected_api_key:
                logger.warning(f"유효하지 않은 API 키: {request.remote_addr}")
                return jsonify({"status": "error", "message": "유효하지 않은 API 키"}), 401
        
        # PnL 업데이트 실행
        exec_manager._update_trade_pnl()
        
        return jsonify({
            "status": "success",
            "message": "PnL 업데이트 작업이 시작되었습니다"
        })
        
    except Exception as e:
        logger.exception(f"PnL 업데이트 중 오류 발생: {e}")
        return jsonify({
            "status": "error",
            "message": f"오류 발생: {str(e)}"
        }), 500

@app.route('/settings', methods=['GET'])
def settings():
    """
    현재 거래 설정 조회 엔드포인트
    
    현재 적용된 거래 설정을 반환합니다.
    """
    try:
        # API 키 검증
        api_key = request.headers.get('X-API-Key')
        if trade_settings.get("require_api_key", False):
            expected_api_key = trade_settings.get("api_key", "")
            if not api_key or api_key != expected_api_key:
                logger.warning(f"유효하지 않은 API 키: {request.remote_addr}")
                return jsonify({"status": "error", "message": "유효하지 않은 API 키"}), 401
        
        # 민감한 정보 제외
        safe_settings = trade_settings.copy()
        if "api_key" in safe_settings:
            safe_settings["api_key"] = "****"
        
        return jsonify({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "settings": safe_settings
        })
        
    except Exception as e:
        logger.exception(f"설정 조회 중 오류 발생: {e}")
        return jsonify({
            "status": "error",
            "message": f"설정 조회 중 오류 발생: {str(e)}"
        }), 500

def start_server(host='0.0.0.0', port=8001):
    """
    실행 서버 시작
    
    Args:
        host: 서버 호스트 (기본값: 0.0.0.0)
        port: 서버 포트 (기본값: 8001)
    """
    logger.info(f"실행 서버 시작: {host}:{port}")
    logger.info(f"지원되는 심볼: {', '.join(config.get_supported_symbols())}")
    
    # 서버 시작
    app.run(host=host, port=port, debug=False, threaded=True)

if __name__ == "__main__":
    start_server()
