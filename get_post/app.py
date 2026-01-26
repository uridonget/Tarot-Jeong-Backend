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
    특정 ID의 게시글 하나를 조회하여 반환합니다.
    """
    logger.info(f"Request received: {event}")
    
    try:
        # 1. 경로 파라미터에서 'post_id' 추출
        path_params = event.get('pathParameters')
        if not path_params or 'post_id' not in path_params:
            return {"statusCode": 400, "body": json.dumps({"error": "post_id is required in path"})}
        
        post_id = path_params['post_id']

        # 2. 데이터베이스에서 특정 게시글 조회
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # users 테이블과 JOIN하여 작성자 닉네임과 프로필 이미지 URL도 함께 가져옴
            fetch_query = """
                SELECT
                    p.id,
                    p.title,
                    p.content,
                    p.created_at,
                    p.user_id,
                    u.nickname,
                    u.profile_image_url
                FROM public.posts p
                JOIN public.users u ON p.user_id = u.id
                WHERE p.id = %s AND p.is_deleted = FALSE;
            """
            cursor.execute(fetch_query, (post_id,))
            post = cursor.fetchone()

        # 3. 게시글이 없는 경우 404 반환
        if not post:
            return {"statusCode": 404, "body": json.dumps({"error": "Post not found"})}

        # id(uuid)와 created_at(datetime)을 문자열로 변환
        post['id'] = str(post['id'])
        post['user_id'] = str(post['user_id'])
        post['created_at'] = post['created_at'].isoformat()
        
        logger.info(f"게시글 조회 성공. ID: {post_id}")

        # 4. 성공 응답 반환
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(post),
        }

    except psycopg2.Error as e:
        logger.error(f"데이터베이스 오류 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Database error occurred"})}
    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred"})}
