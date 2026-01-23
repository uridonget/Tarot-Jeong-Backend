import json
import logging
import os
import boto3
import psycopg2
from psycopg2 import extras

# 로거 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- 전역 변수 ---
ssm_client = None
db_conn = None
db_conn_string = None

# --- 환경 변수 ---
DB_CONN_STRING_PARAM_PATH = os.environ.get("DB_CONN_STRING_PARAM_PATH")

# --- Helper Functions for DB ---

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
    """
    크레딧이 3보다 적은 모든 사용자의 크레딧을 3으로 설정합니다.
    """
    logger.info("크레딧 업데이트 로직을 시작합니다.")
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 크레딧이 3보다 적은 사용자를 대상으로 크레딧을 3으로 업데이트
            cursor.execute("UPDATE public.users SET credit = 3 WHERE credit < 3")
            
            # 영향을 받은 행의 수를 가져옵니다.
            updated_count = cursor.rowcount
            
            logger.info(f"총 {updated_count}명의 사용자의 크레딧을 3으로 업데이트했습니다.")
            
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Credit update successful.",
                    "updated_users": updated_count
                })
            }

    except psycopg2.Error as e:
        logger.error(f"데이터베이스 오류 발생: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Database error", "details": str(e)})}
    except Exception as e:
        logger.error(f"처리 중 예외 발생: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "An unexpected error occurred", "details": str(e)})}
    finally:
        # 이 함수는 주기적으로 실행되므로 연결을 유지할 필요가 적습니다.
        # 그러나 Lambda 컨텍스트 재사용을 위해 연결을 열어두는 것이 일반적입니다.
        pass
