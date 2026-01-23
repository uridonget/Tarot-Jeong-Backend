import json
import logging
import os
import random
import boto3
import google.generativeai as genai
import psycopg2
from psycopg2 import extras

# 로거 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- 전역 변수 ---
ssm_client = None
gemini_api_key = None
db_conn = None
db_conn_string = None

# --- 환경 변수 ---
GEMINI_API_KEY_PARAM_PATH = os.environ.get("GEMINI_API_KEY_PARAM_PATH")
DB_CONN_STRING_PARAM_PATH = os.environ.get("DB_CONN_STRING_PARAM_PATH") # template.yaml에 추가 필요

# --- 데이터 로드 ---
TAROT_CARDS_DATA = []
try:
    with open("cards.json", "r", encoding="utf-8") as f:
        TAROT_CARDS_DATA = json.load(f)["cards"]
except Exception as e:
    logger.error(f"cards.json 파일 로드 실패: {e}")

# --- Helper Functions for AWS/DB ---

def get_gemini_api_key():
    global gemini_api_key, ssm_client
    if gemini_api_key:
        return gemini_api_key
    
    if not GEMINI_API_KEY_PARAM_PATH:
        raise ValueError("GEMINI_API_KEY_PARAM_PATH 환경 변수가 설정되지 않았습니다.")
        
    if ssm_client is None:
        ssm_client = boto3.client("ssm")
        
    try:
        parameter = ssm_client.get_parameter(Name=GEMINI_API_KEY_PARAM_PATH, WithDecryption=True)
        gemini_api_key = parameter["Parameter"]["Value"]
        return gemini_api_key
    except Exception as e:
        logger.error(f"SSM Parameter Store에서 Gemini API Key 로드 실패: {e}")
        raise

def get_db_connection_string():
    global db_conn_string, ssm_client
    if db_conn_string:
        return db_conn_string

    if not DB_CONN_STRING_PARAM_PATH:
        raise ValueError("DB_CONN_STRING_PARAM_PATH 환경 변수가 설정되지 않았습니다.")

    if ssm_client is None:
        ssm_client = boto3.client("ssm")
        
    try:
        parameter = ssm_client.get_parameter(Name=DB_CONN_STRING_PARAM_PATH, WithDecryption=True)
        db_conn_string = parameter["Parameter"]["Value"]
        return db_conn_string
    except Exception as e:
        logger.error(f"SSM Parameter Store에서 DB 연결 문자열 로드 실패: {e}")
        raise

def get_db_connection():
    global db_conn
    try:
        if db_conn and db_conn.closed == 0:
            db_conn.cursor().execute("SELECT 1")
            return db_conn
    except psycopg2.OperationalError:
        logger.warning("기존 DB 연결이 유효하지 않아 재연결합니다.")
        db_conn = None

    conn_string = get_db_connection_string()
    try:
        db_conn = psycopg2.connect(conn_string)
        db_conn.autocommit = True
        return db_conn
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}")
        raise

# --- Main Lambda Handler ---

def lambda_handler(event, context):
    logger.info(f"Request received: {event}")
    
    conn = None
    try:
        # 1. 사용자 정보 및 요청 본문 파싱
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = authorizer_context.get('user_id')
        if not user_id:
            return {"statusCode": 401, "body": json.dumps({"error": "User ID not found in token"}, ensure_ascii=False)}

        body = json.loads(event.get("body", "{}"))
        user_concern = body.get("concern")
        if not user_concern:
            return {"statusCode": 400, "body": json.dumps({"error": "고민 내용(concern)이 필요합니다."}, ensure_ascii=False)}

        # 2. 크레딧 확인
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute("SELECT credit FROM public.users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if user is None or user['credit'] < 1:
                return {
                    "statusCode": 402, # Payment Required
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "크레딧이 부족합니다. 크레딧을 충전해주세요."}, ensure_ascii=False)
                }

        # 3. 타로카드 선택 (기존 로직 유지)
        if not TAROT_CARDS_DATA:
            raise ValueError("타로카드 데이터를 로드하지 못했습니다.")
            
        selected_indices = random.sample(range(len(TAROT_CARDS_DATA)), 3)
        selected_cards_info = []
        for index in selected_indices:
            card = TAROT_CARDS_DATA[index]
            orientation = random.choice(["정방향", "역방향"])
            meaning_key = "upright" if orientation == "정방향" else "reversed"
            selected_cards_info.append({
                "name": card["name"],
                "orientation": orientation,
                "meaning": card[meaning_key],
                "image_url": f"https://d2yzln6f92x3hm.cloudfront.net/public/cards/{card['index']}.png"
            })

        # 4. Gemini API 호출
        api_key = get_gemini_api_key()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")

        prompt = f"""
        You are a helpful assistant that provides tarot readings in a structured JSON format. Your response MUST be a single, valid JSON object and nothing else. Do not include ```json markdown delimiters. Based on the user's concern and the drawn cards, provide a detailed tarot reading in Korean.
        ## User's Concern: {user_concern}
        ## Drawn Cards:
        - First: {selected_cards_info[0]['name']} ({selected_cards_info[0]['orientation']}) - {selected_cards_info[0]['meaning']}
        - Second: {selected_cards_info[1]['name']} ({selected_cards_info[1]['orientation']}) - {selected_cards_info[1]['meaning']}
        - Third: {selected_cards_info[2]['name']} ({selected_cards_info[2]['orientation']}) - {selected_cards_info[2]['meaning']}
        ## Reading Guidelines: Provide detailed interpretations for past, present, future, and an overall summary. Each should be 3-4 sentences in an empathetic tone.
        ## Required JSON Output Format: {{"past": "", "present": "", "future": "", "summary": ""}}
        """

        try:
            gemini_response = model.generate_content(prompt)
            json_text = gemini_response.text.strip().replace("```json", "").replace("```", "")
            reading_data = json.loads(json_text)
        except Exception as e:
            logger.error(f"Gemini API 호출 또는 JSON 파싱 오류: {e}")
            return {"statusCode": 500, "body": json.dumps({"error": "AI 모델 응답 처리 실패"}, ensure_ascii=False)}

        # 5. 크레딧 차감 (Gemini 호출 성공 후)
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE public.users SET credit = credit - 1 WHERE id = %s", (user_id,))
            logger.info(f"사용자(id: {user_id})의 크레딧을 1 차감했습니다.")
        except Exception as e:
            # 크레딧 차감에 실패하더라도 사용자는 이미 결과를 받았으므로 로깅만 하고 넘어갑니다.
            logger.error(f"사용자(id: {user_id}) 크레딧 차감 실패: {e}")

        # 6. 최종 결과 반환
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "cards": selected_cards_info,
                "reading": reading_data
            }, ensure_ascii=False),
        }

    except psycopg2.Error as e:
        logger.error(f"데이터베이스 오류: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "데이터베이스 오류가 발생했습니다."}, ensure_ascii=False)}
    except ValueError as e:
        logger.error(f"설정 오류: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)}, ensure_ascii=False)}
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "서버에서 예상치 못한 오류가 발생했습니다."}, ensure_ascii=False)}
    finally:
        # Lambda 실행 컨텍스트가 유지되는 동안 연결을 재사용하므로, 여기서 닫지 않습니다.
        pass
