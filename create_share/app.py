import json
import logging
import os
import psycopg2
from psycopg2 import extras
import uuid

# get_profile/app.py와 동일한 DB 연결 로직을 가져옵니다.
# ---------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

db_conn = None
db_conn_string = None
ssm_client = None
DB_CONN_STRING_PARAM_PATH = os.environ.get("DB_CONN_STRING_PARAM_PATH")

def get_db_connection_string():
    global db_conn_string, ssm_client
    if db_conn_string: return db_conn_string
    if not DB_CONN_STRING_PARAM_PATH: raise ValueError("DB_CONN_STRING_PARAM_PATH 환경 변수가 설정되지 않았습니다.")
    
    import boto3
    if ssm_client is None: ssm_client = boto3.client("ssm")
    
    logger.info("Parameter Store에서 DB 연결 문자열을 가져옵니다.")
    parameter = ssm_client.get_parameter(Name=DB_CONN_STRING_PARAM_PATH, WithDecryption=True)
    db_conn_string = parameter["Parameter"]["Value"]
    return db_conn_string

def get_db_connection():
    global db_conn
    if db_conn:
        try:
            db_conn.cursor().execute("SELECT 1")
            return db_conn
        except psycopg2.OperationalError:
            db_conn = None
    
    conn_string = get_db_connection_string()
    db_conn = psycopg2.connect(conn_string)
    db_conn.autocommit = True
    return db_conn
# ---------------------------------------------------

def lambda_handler(event, context):
    """
    타로 리딩 결과를 DB에 저장하고 공유 ID를 반환합니다.
    """
    logger.info(f"Request received: {event}")
    
    conn = None
    try:
        # 1. Authorizer로부터 사용자 ID 추출
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = authorizer_context.get('user_id')

        if not user_id:
            return {"statusCode": 401, "body": json.dumps({"error": "User ID not found in token"})}

        # 2. 요청 Body에서 타로 리딩 데이터 추출
        try:
            reading_data = json.loads(event.get("body", "{}"))
            if not reading_data:
                return {"statusCode": 400, "body": json.dumps({"error": "Reading data is required in the body"})}
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON format in request body"})}

        # 3. 데이터베이스에 저장
        conn = get_db_connection()
        cursor = conn.cursor()

        insert_query = """
            INSERT INTO public.shared_readings (reading_data, user_id)
            VALUES (%s, %s)
            RETURNING id;
        """
        # reading_data를 JSON 문자열로 변환하여 저장
        cursor.execute(insert_query, (json.dumps(reading_data), user_id))
        
        new_share_id = cursor.fetchone()[0]
        logger.info(f"새로운 공유 리딩 생성 완료. ID: {new_share_id}")

        cursor.close()

        # 4. 성공 응답 반환
        return {
            "statusCode": 201, # 201 Created
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"share_id": str(new_share_id)}),
        }

    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred"})}
