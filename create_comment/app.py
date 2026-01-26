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
    if db_conn_string: return db_conn_string
    if not DB_CONN_STRING_PARAM_PATH: raise ValueError("DB_CONN_STRING_PARAM_PATH 환경 변수가 설정되지 않았습니다.")
    
    import boto3
    if ssm_client is None: ssm_client = boto3.client("ssm")
    
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
    특정 게시글에 새로운 댓글을 작성합니다.
    """
    logger.info(f"Request received: {event}")
    
    try:
        # 1. Authorizer로부터 사용자 ID 추출
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = authorizer_context.get('user_id')
        if not user_id:
            return {"statusCode": 401, "body": json.dumps({"error": "User ID not found in token"})}

        # 2. 경로 파라미터에서 'post_id' 추출
        path_params = event.get('pathParameters')
        if not path_params or 'post_id' not in path_params:
            return {"statusCode": 400, "body": json.dumps({"error": "post_id is required in path"})}
        post_id = path_params['post_id']

        # 3. 요청 Body에서 댓글 내용(content) 추출
        try:
            body = json.loads(event.get("body", "{}"))
            content = body.get('content')
            if not content or not content.strip():
                return {"statusCode": 400, "body": json.dumps({"error": "Comment content is required"})}
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON format in request body"})}

        # 4. 데이터베이스에 댓글 저장
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            insert_query = """
                INSERT INTO public.comments (post_id, user_id, content)
                VALUES (%s, %s, %s)
                RETURNING id, created_at;
            """
            cursor.execute(insert_query, (post_id, user_id, content))
            new_comment_data = cursor.fetchone()

        new_comment_id = str(new_comment_data['id'])
        new_comment_created_at = new_comment_data['created_at'].isoformat()
        logger.info(f"새로운 댓글 생성 완료. ID: {new_comment_id}")

        # 5. 성공 응답 반환 (생성된 댓글의 주요 정보 포함)
        return {
            "statusCode": 201,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "message": "Comment created successfully",
                "comment_id": new_comment_id,
                "created_at": new_comment_created_at
            }),
        }

    except psycopg2.Error as e:
        logger.error(f"데이터베이스 오류 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Database error occurred"})}
    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred"})}
