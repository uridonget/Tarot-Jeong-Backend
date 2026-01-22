import json
import logging
import os
import random
import boto3
import google.generativeai as genai

# 로거 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS 클라이언트 및 Gemini API Key 캐시를 위한 전역 변수
ssm_client = None
gemini_api_key = None

# 환경 변수에서 Parameter Store 경로를 가져옵니다.
GEMINI_API_KEY_PARAM_PATH = os.environ.get("GEMINI_API_KEY_PARAM_PATH")

# Tarot Cards Data (패키징된 JSON 파일에서 로드)
TAROT_CARDS_DATA = []
try:
    with open("cards.json", "r", encoding="utf-8") as f:
        TAROT_CARDS_DATA = json.load(f)["cards"]
except FileNotFoundError:
    logger.error("cards.json 파일을 찾을 수 없습니다. Lambda 패키징 확인이 필요합니다.")
    TAROT_CARDS_DATA = [] # 에러 발생 시 빈 리스트로 초기화
except json.JSONDecodeError:
    logger.error("cards.json 파일의 JSON 형식이 올바르지 않습니다.")
    TAROT_CARDS_DATA = [] # 에러 발생 시 빈 리스트로 초기화


def get_gemini_api_key():
    """
    AWS Systems Manager Parameter Store에서 Gemini API Key를 가져옵니다.
    한 번 가져온 키는 Lambda 실행 컨텍스트 내에서 캐싱하여 재사용합니다.
    """
    global gemini_api_key
    global ssm_client

    # 키가 이미 캐시되어 있으면 즉시 반환합니다.
    if gemini_api_key:
        return gemini_api_key

    logger.info("캐시된 Gemini API Key가 없어 Parameter Store에서 가져옵니다.")

    if not GEMINI_API_KEY_PARAM_PATH:
        logger.error("GEMINI_API_KEY_PARAM_PATH 환경 변수가 설정되지 않았습니다.")
        raise ValueError("Gemini API Key 경로가 설정되지 않았습니다.")

    # Boto3 SSM 클라이언트를 초기화합니다.
    if ssm_client is None:
        ssm_client = boto3.client("ssm")

    try:
        # Parameter Store에서 SecureString 값을 가져옵니다.
        parameter = ssm_client.get_parameter(
            Name=GEMINI_API_KEY_PARAM_PATH, WithDecryption=True
        )
        gemini_api_key = parameter["Parameter"]["Value"]
        logger.info("Gemini API Key를 성공적으로 가져와 캐싱했습니다.")
        return gemini_api_key
    except Exception as e:
        logger.error(f"Parameter Store에서 Gemini API Key를 가져오는 데 실패했습니다: {e}")
        raise


def lambda_handler(event, context):
    """
    사용자의 고민과 3장의 타로카드를 Gemini API에 보내 타로점 해석을 받습니다.
    """
    logger.info(f"Request received: {event}")

    # 1. 사용자 고민(prompt) 추출
    try:
        body = json.loads(event.get("body", "{}"))
        user_concern = body.get("concern")

        if not user_concern:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "고민 내용(concern)이 필요합니다."}),
            }
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "유효하지 않은 JSON 형식입니다."}),
        }

    # 2. 타로카드 3장 랜덤 선택 및 방향 지정
    if not TAROT_CARDS_DATA:
         return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "타로카드 데이터를 로드하지 못했습니다. 관리자에게 문의하세요."}),
        }

    selected_indices = random.sample(range(len(TAROT_CARDS_DATA)), 3)
    selected_cards_info = []
    for i, index in enumerate(selected_indices):
        card = TAROT_CARDS_DATA[index]
        orientation_str = random.choice(["정방향", "역방향"])
        meaning_key = "upright" if orientation_str == "정방향" else "reversed"
        selected_cards_info.append(
            {
                "name": card["name"],
                "orientation": orientation_str,
                "meaning": card[meaning_key],
                # "image_url": f"{settings.CLOUDFRONT_ENDPOINT}/public/cards/{card['index']}.png", # Frontend에서 처리
            }
        )
    
    # 3. Gemini API Key 설정 및 모델 구성
    try:
        api_key = get_gemini_api_key()
        genai.configure(api_key=api_key)
        # model = genai.GenerativeModel("models/gemini-2.5-flash-lite")
        model = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")
    except Exception as e:
        logger.error(f"Gemini API 설정 실패: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "AI 모델 설정에 실패했습니다."}),
        }

    # 4. 프롬프트 구성 (샘플 코드와 동일하게)
    prompt = f"""
    You are a helpful assistant that provides tarot readings in a structured JSON format.
    Your response MUST be a single, valid JSON object and nothing else. Do not include ```json markdown delimiters.

    Based on the user's concern and the drawn cards, provide a detailed tarot reading.
    You must make response in Korean.

    ## User's Concern
    {user_concern}

    ## Drawn Cards
    - First Card: {selected_cards_info[0]['name']} ({selected_cards_info[0]['orientation']}) ({selected_cards_info[0]['meaning']})
    - Second Card: {selected_cards_info[1]['name']} ({selected_cards_info[1]['orientation']}) ({selected_cards_info[1]['meaning']})
    - Third Card: {selected_cards_info[2]['name']} ({selected_cards_info[2]['orientation']}) ({selected_cards_info[2]['meaning']})

    ## Reading Guidelines
    - Provide a detailed interpretation for each card in its position (Past, Present, Future).
    - Provide an overall summary and advice.
    - Each interpretation should be at least 3-4 sentences long and written in Korean with an empathetic tone.

    ## Required JSON Output Format
    ```json
    {{
      "past": "",
      "present": "",
      "future": "",
      "summary": ""
    }}
    ```
    """

    # 5. Gemini API 호출 및 응답 처리
    try:
        gemini_response = model.generate_content(prompt)
        json_text = gemini_response.text.strip().replace("```json", "").replace("```", "")
        reading_data = json.loads(json_text)
    except Exception as e:
        logger.error(f"Gemini API 호출 또는 JSON 파싱 오류: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "AI 모델 응답을 처리하는 데 실패했습니다."}),
        }

    # 6. 최종 결과 반환
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*", # CORS 설정
        },
        "body": json.dumps({
            "cards": selected_cards_info,
            "reading": reading_data
        }),
    }
