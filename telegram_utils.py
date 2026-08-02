import requests
import logging

def send_telegram_alert(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """
    텔레그램 봇 API를 사용하여 메시지를 전송합니다.
    
    Args:
        token (str): 텔레그램 봇 토큰
        chat_id (str): 메시지를 수신할 채팅방 ID
        text (str): 전송할 메시지 내용 (HTML 포맷 지원)
        
    Returns:
        tuple[bool, str]: (성공 여부, 결과 메시지)
    """
    if not token or not chat_id:
        return False, "봇 토큰이나 Chat ID가 설정되지 않았습니다."
        
    # 기본 더미 텍스트 방지
    if token == "YOUR_BOT_TOKEN_HERE" or chat_id == "YOUR_CHAT_ID_HERE":
        return False, "텔레그램 봇 토큰과 Chat ID를 설정 파일(secrets.toml)에 올바르게 입력해주세요."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        # 텔레그램 API 자체의 ok 필드 확인
        data = response.json()
        if data.get("ok"):
            return True, "메시지가 성공적으로 전송되었습니다."
        else:
            return False, f"API 에러: {data.get('description', '알 수 없는 에러')}"
            
    except requests.exceptions.RequestException as e:
        logging.error(
            "Telegram API request failed (%s)",
            type(e).__name__,
        )
        return False, "텔레그램 네트워크 또는 API 요청 오류가 발생했습니다."
