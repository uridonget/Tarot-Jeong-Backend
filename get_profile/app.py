import json
import logging
import os
import boto3
import psycopg2
from psycopg2 import extras

# 로거 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS 클라이언트 및 DB 연결 캐시를 위한 전역 변수
ssm_client = None
db_conn = None
db_conn_string = None

# 환경 변수에서 Parameter Store 경로를 가져옵니다.
DB_CONN_STRING_PARAM_PATH = os.environ.get("DB_CONN_STRING_PARAM_PATH")

def get_db_connection_string():
    """
    AWS Systems Manager Parameter Store에서 Supabase DB 연결 문자열을 가져옵니다.
    한 번 가져온 값은 Lambda 실행 컨텍스트 내에서 캐싱하여 재사용합니다.
    """
    global db_conn_string
    global ssm_client

    if db_conn_string:
        return db_conn_string

    logger.info("캐시된 DB 연결 문자열이 없어 Parameter Store에서 가져옵니다.")

    if not DB_CONN_STRING_PARAM_PATH:
        logger.error("DB_CONN_STRING_PARAM_PATH 환경 변수가 설정되지 않았습니다.")
        raise ValueError("DB 연결 문자열 경로가 설정되지 않았습니다.")

    if ssm_client is None:
        ssm_client = boto3.client("ssm")

    try:
        parameter = ssm_client.get_parameter(Name=DB_CONN_STRING_PARAM_PATH, WithDecryption=True)
        db_conn_string = parameter["Parameter"]["Value"]
        logger.info("DB 연결 문자열을 성공적으로 가져와 캐싱했습니다.")
        return db_conn_string
    except Exception as e:
        logger.error(f"Parameter Store에서 DB 연결 문자열을 가져오는 데 실패했습니다: {e}")
        raise

def get_db_connection():
    """
    데이터베이스 연결을 생성하고 반환합니다.
    기존에 열린 연결이 있으면 재사용합니다.
    """
    global db_conn
    if db_conn:
        # 연결이 유효한지 확인 (간단한 방법)
        try:
            db_conn.cursor().execute("SELECT 1")
            return db_conn
        except psycopg2.OperationalError:
            logger.info("기존 DB 연결이 끊어져 재연결합니다.")
            db_conn = None # 연결이 끊어졌으므로 None으로 설정

    logger.info("새로운 DB 연결을 생성합니다.")
    conn_string = get_db_connection_string()
    try:
        db_conn = psycopg2.connect(conn_string)
        db_conn.autocommit = True # Pooler 사용 시 auto-commit 모드가 권장됨
        return db_conn
    except Exception as e:
        logger.error(f"DB 연결에 실패했습니다: {e}")
        raise

def lambda_handler(event, context):
    """
    사용자 프로필을 조회하거나, 없는 경우 생성합니다.
    """
    logger.info(f"Request received: {event}")
    
    conn = None
    try:
        # Authorizer가 전달한 사용자 정보를 추출합니다.
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = authorizer_context.get('user_id')
        email = authorizer_context.get('email')
        full_name = authorizer_context.get('full_name') # Authorizer에서 전달받은 닉네임
        profile_image_url = authorizer_context.get('profile_image_url') # Authorizer에서 전달받은 프로필 이미지 URL

        if not user_id:
            return {"statusCode": 401, "body": json.dumps({"error": "User ID not found in token"})}

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=extras.DictCursor)

        # 1. 사용자 조회 (Supabase 'auth.users'의 id는 public.users 테이블의 id와 동일해야 함)
        # 'public.users' 테이블이 있다고 가정합니다.
        cursor.execute("SELECT * FROM public.users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        # 2. 사용자가 없으면 새로 생성 (자동 회원가입)
        if not user:
            logger.info(f"사용자(id: {user_id})가 없어 새로 생성합니다.")
            # INSERT 쿼리 실행. nickname과 profile_image_url 필드를 추가합니다.
            cursor.execute(
                "INSERT INTO public.users (id, email, nickname, profile_image_url) VALUES (%s, %s, %s, %s) RETURNING *",
                (user_id, email, full_name, profile_image_url)
            )
            user = cursor.fetchone()
            logger.info(f"새로운 사용자 생성 완료: {user}")

        else:
            logger.info(f"기존 사용자 정보를 반환합니다: {user}")
            
        # JSON으로 직렬화하기 위해 dict로 변환
        user_profile = dict(user) if user else {}
        
        # 'created_at', 'updated_at' 같은 datetime 객체는 문자열로 변환
        for key, value in user_profile.items():
            if hasattr(value, 'isoformat'):
                user_profile[key] = value.isoformat()

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(user_profile),
        }

    except psycopg2.Error as e:
        logger.error(f"데이터베이스 오류 발생: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Database error", "details": str(e)})}
    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred", "details": str(e)})}
    finally:
        # 이 예제에서는 Lambda 컨텍스트 간 연결을 캐싱하므로 연결을 닫지 않습니다.
        # 만약 매번 새로운 연결을 만든다면 여기서 cursor.close()와 conn.close()를 호출해야 합니다.
        pass