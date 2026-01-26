import json
import logging
import os
import psycopg2
from psycopg2 import extras

# 로거 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 전역 변수로 DB 연결 관리
db_conn = None
db_conn_string = None
ssm_client = None
DB_CONN_STRING_PARAM_PATH = os.environ.get("DB_CONN_STRING_PARAM_PATH")

def get_db_connection_string():
    """Parameter Store에서 데이터베이스 연결 문자열을 가져옵니다."""
    global db_conn_string, ssm_client
    if db_conn_string:
        return db_conn_string
    if not DB_CONN_STRING_PARAM_PATH:
        raise ValueError("DB_CONN_STRING_PARAM_PATH 환경 변수가 설정되지 않았습니다.")
    
    import boto3
    if ssm_client is None:
        ssm_client = boto3.client("ssm")
    
    logger.info("Parameter Store에서 DB 연결 문자열을 가져옵니다.")
    parameter = ssm_client.get_parameter(Name=DB_CONN_STRING_PARAM_PATH, WithDecryption=True)
    db_conn_string = parameter["Parameter"]["Value"]
    return db_conn_string

def get_db_connection():
    """데이터베이스 연결을 가져오고, 필요한 경우 새로 생성합니다."""
    global db_conn
    if db_conn:
        try:
            # 연결이 여전히 유효한지 확인
            db_conn.cursor().execute("SELECT 1")
            return db_conn
        except psycopg2.OperationalError:
            db_conn = None
    
    conn_string = get_db_connection_string()
    db_conn = psycopg2.connect(conn_string)
    db_conn.autocommit = True
    return db_conn

def lambda_handler(event, context):
    """
    새로운 게시글을 받아 데이터베이스의 posts 테이블에 저장합니다.
    """
    logger.info(f"Request received: {event}")
    
    conn = None
    try:
        # 1. Authorizer로부터 사용자 ID 추출
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = authorizer_context.get('user_id')

        if not user_id:
            logger.warning("요청에서 사용자 ID를 찾을 수 없습니다.")
            return {
                "statusCode": 401, 
                "body": json.dumps({"error": "User ID not found in token"})
            }

        # 2. 요청 Body에서 게시글 데이터(title, content) 추출
        try:
            body = json.loads(event.get("body", "{}"))
            title = body.get('title')
            content = body.get('content')
            if not title or not content:
                logger.warning("요청 본문에 title 또는 content가 없습니다.")
                return {
                    "statusCode": 400, 
                    "body": json.dumps({"error": "Title and content are required"})
                }
        except json.JSONDecodeError:
            logger.error("요청 본문의 JSON 형식이 잘못되었습니다.")
            return {
                "statusCode": 400, 
                "body": json.dumps({"error": "Invalid JSON format in request body"})
            }

        # 3. 데이터베이스에 게시글 저장
        conn = get_db_connection()
        with conn.cursor() as cursor:
            insert_query = """
                INSERT INTO public.posts (user_id, title, content)
                VALUES (%s, %s, %s)
                RETURNING id;
            """
            cursor.execute(insert_query, (user_id, title, content))
            
            new_post_id = cursor.fetchone()[0]
            logger.info(f"새로운 게시글 생성 완료. ID: {new_post_id}")

        # 4. 성공 응답 반환
        return {
            "statusCode": 201, # 201 Created
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*", # CORS 설정
            },
            "body": json.dumps({"post_id": str(new_post_id)}),
        }

    except psycopg2.Error as e:
        logger.error(f"데이터베이스 오류 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Database error occurred"})}
    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred"})}
