import logging
import jwt
from jwt import PyJWTError, PyJWKClient

# 로거 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# JWKS 클라이언트를 캐싱하기 위한 전역 변수
# 키별로 클라이언트를 저장하여 다른 발급자의 토큰도 처리 가능
jwks_clients = {}

def get_signing_key(token):
    """
    토큰의 발급자(iss)를 기반으로 JWKS 엔드포인트에서 서명 키를 가져옵니다.
    PyJWKClient는 내부적으로 키를 캐싱하여 성능을 향상시킵니다.
    """
    try:
        # 서명을 확인하지 않고 헤더를 먼저 가져옵니다.
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise PyJWTError("토큰 헤더에 'kid'가 없습니다.")

        # 서명을 확인하지 않고 페이로드를 디코딩하여 'iss'를 얻습니다.
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified_payload.get("iss")
        if not issuer:
            raise PyJWTError("토큰 페이로드에 'iss'가 없습니다.")

        # 발급자별로 JWKS 클라이언트를 캐싱합니다.
        if issuer not in jwks_clients:
            jwks_url = f"{issuer}/.well-known/jwks.json"
            logger.info(f"{issuer}에 대한 JWKS 클라이언트를 생성합니다. URL: {jwks_url}")
            jwks_clients[issuer] = PyJWKClient(jwks_url)
        
        jwks_client = jwks_clients[issuer]
        
        # 토큰의 kid에 해당하는 서명 키를 가져옵니다.
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return signing_key.key

    except (PyJWTError, Exception) as e:
        logger.error(f"서명 키를 가져오는 데 실패했습니다: {e}")
        raise

def lambda_handler(event, context):
    """
    API Gateway Custom Authorizer의 메인 핸들러입니다.
    Authorization 헤더의 JWT를 검증하고 IAM 정책을 반환합니다.
    """
    logger.info(f"Authorizer 이벤트 수신: {event}")

    # 리소스 ARN 생성
    try:
        # REST API의 methodArn에서 스테이지까지만 추출하여 와일드카드 ARN 생성
        method_arn = event.get("methodArn", "")
        arn_parts = method_arn.split(":")
        api_gateway_arn_parts = arn_parts[5].split("/")
        
        # arn:aws:execute-api:{region}:{account_id}:{api_id}/{stage}/*
        region = arn_parts[3]
        account_id = arn_parts[4]
        api_id = api_gateway_arn_parts[0]
        stage = api_gateway_arn_parts[1]
        
        resource = f"arn:aws:execute-api:{region}:{account_id}:{api_id}/{stage}/*"
        logger.info(f"와일드카드 리소스 ARN을 생성했습니다: {resource}")

    except (KeyError, AttributeError, IndexError):
        # ARN 파싱 실패 시, 들어온 methodArn을 그대로 사용하거나 전체 와일드카드로 대체
        resource = event.get("methodArn", "*") 
        logger.warning(f"methodArn 파싱에 실패하여 Resource ARN을 '{resource}'로 설정합니다.")


    # 대소문자를 구분하지 않고 Authorization 헤더를 찾습니다.
    headers = event.get("headers", {})
    auth_header = next((value for key, value in headers.items() if key.lower() == "authorization"), None)
    
    # REST API의 'authorizationToken' 필드도 확인합니다.
    token = auth_header or event.get('authorizationToken')

    if not token:
        logger.warning("Authorization 토큰이 없습니다.")
        return generate_policy("user", "Deny", resource, context={"error": "Authorization token missing"})

    # "Bearer " 접두사 및 앞뒤 공백 제거
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:]

    try:
        # JWKS에서 올바른 공개키를 가져옵니다.
        public_key = get_signing_key(token)

        # 공개키와 ES256 알고리즘을 사용하여 JWT를 디코딩하고 검증합니다.
        # Supabase JWT는 'aud' (audience) 클레임 검증이 필요할 수 있습니다.
        decoded = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": True},
            audience="authenticated",
        )

        principal_id = decoded.get("sub")
        if not principal_id:
            logger.warning("토큰에 'sub' 클레임이 없습니다.")
            raise PyJWTError("Invalid token claims")

        logger.info(f"토큰이 성공적으로 검증되었습니다. 사용자 ID: {principal_id}")
        
        # 후속 Lambda 함수에 전달할 컨텍스트를 생성합니다.
        user_metadata = decoded.get("user_metadata", {})
        full_name = user_metadata.get("full_name")
        avatar_url = user_metadata.get("avatar_url") # avatar_url 추가

        authorizer_context = {
            "user_id": str(principal_id or ''),
            "email": str(decoded.get("email") or ''),
            "role": str(decoded.get("role") or ''),
            "full_name": str(full_name or ''), # Google 닉네임을 컨텍스트에 추가
            "profile_image_url": str(avatar_url or ''), # 프로필 이미지 URL 추가
        }
        
        return generate_policy(principal_id, "Allow", resource, authorizer_context)

    except PyJWTError as e:
        logger.error(f"JWT 검증 실패: {e}")
        return generate_policy("user", "Deny", resource, context={"error": str(e)})
    except Exception as e:
        logger.error(f"Authorizer 처리 중 예외 발생: {e}")
        return generate_policy("user", "Deny", resource, context={"error": "Internal server error"})

def generate_policy(principal_id, effect, resource, context=None):
    """
    API Gateway Authorizer가 요구하는 형식의 IAM 정책 응답을 생성합니다.
    """
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context

    logger.info(f"생성된 정책: {policy}")
    return policy
