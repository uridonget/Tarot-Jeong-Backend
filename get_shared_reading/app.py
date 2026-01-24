import json
import logging
import os
import psycopg2
from psycopg2 import extras

# CreateShareFunction과 동일한 DB 연결 로직
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
    share_id로 공유된 타로 리딩 결과를 조회합니다. (인증 불필요)
    """
    logger.info(f"Request received: {event}")

    try:
        # 1. 경로 파라미터에서 share_id 추출
        share_id = event.get('pathParameters', {}).get('share_id')
        if not share_id:
            return {"statusCode": 400, "body": json.dumps({"error": "share_id is required"})}

        # 2. 데이터베이스에서 결과 조회
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=extras.DictCursor)

        query = "SELECT reading_data FROM public.shared_readings WHERE id = %s;"
        cursor.execute(query, (share_id,))
        
        result = cursor.fetchone()
        cursor.close()

        # 3. 결과 반환
        if result and 'reading_data' in result:
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps(result['reading_data']),
            }
        else:
            return {"statusCode": 404, "body": json.dumps({"error": "Reading not found"})}

    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred"})}
