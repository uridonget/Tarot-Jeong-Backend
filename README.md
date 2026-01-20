# 타로정 백엔드

이 저장소는 타로정 프로젝트의 백엔드 서비스 코드를 포함합니다. AWS 서버리스 아키텍처와 Go 언어를 기반으로 구축됩니다.

## 🏛️ 아키텍처 개요

이 백엔드는 현대적이고 분리된 서버리스 아키텍처를 따릅니다:

-   **API 계층 (AWS API Gateway):** 모든 인바운드 HTTP 요청의 단일 진입점 역할을 하며, 적절한 람다 함수로 라우팅합니다.
-   **인증 (API Gateway 람다 Authorizer & Supabase):**
    -   사용자 식별 및 JWT 발급은 **Supabase Auth**에서 관리합니다.
    -   전용 **람다 Authorizer** 함수는 보호된 모든 API 호출에서 Supabase가 발급한 JWT를 검증하여, 커스텀 인증 로직 구현 없이 보안을 보장합니다.
-   **컴퓨팅 (AWS Lambda):** 비즈니스 로직은 작고 단일 목적의 Go 함수들로 캡슐화됩니다.
-   **데이터 계층:**
    -   **주 데이터베이스 (Supabase DB - PostgreSQL):** 사용자 프로필 및 리딩 기록과 같은 영구적인 애플리케이션 데이터를 저장합니다.
    -   **캐시:** (현재 캐시 계층은 없습니다. 필요한 경우 추후 추가될 수 있습니다.)
-   **외부 서비스:**
    -   **이메일 (AWS SES):** 트랜잭션 이메일을 처리합니다.
    -   **AI 모델 (Google Gemini):** 타로 카드 해석을 제공합니다.
    -   **파일 저장소 & CDN (AWS S3 & CloudFront):** 생성된 공유 가능한 HTML 페이지를 저장하고 전송합니다.

## 🔑 환경 설정 및 필수 사항

이 백엔드를 실행하고 배포하려면 다음 서비스들을 설정하고 해당 자격 증명을 **AWS Systems Manager Parameter Store**에 `SecureString` 타입으로 저장해야 합니다.

### 1. Supabase

-   **조치 사항:**
    1.  Supabase 프로젝트를 생성해주세요.
    2.  인증 설정에서 이메일/비밀번호 인증을 활성화해주세요.
    3.  제공된 SQL 스크립트를 실행하여 `profiles` 테이블을 생성해주세요.
-   **저장할 파라미터:**
    -   `/tarot/supabase/db_conn_str`: Supabase 프로젝트 설정에서 데이터베이스 연결 문자열.
    -   `/tarot/supabase/jwt_secret`: Supabase API 설정에서 JWT Secret.

### 2. AWS

-   **조치 사항:**
    1.  **AWS SES**에서 이메일을 보낼 도메인 또는 개별 이메일 주소를 확인(Verified) 상태로 만들어주세요.
    2.  **AWS CloudFront**에서 URL 서명에 사용할 키 페어(공개 키/개인 키)를 생성해주세요.
-   **저장할 파라미터:**
    -   `/tarot/cloudfront/key_id`: CloudFront 공개 키 ID.
    -   `/tarot/cloudfront/private_key`: `.pem` 개인 키 파일의 내용 전체.

### 3. Google AI (Gemini)

-   **조치 사항:** Google AI Studio에서 Gemini API 키를 발급받아주세요.
-   **저장할 파라미터:**
    -   `/tarot/gemini/api_key`: Gemini API 키.

## 💻 개발

프로젝트는 표준 Go 개발 관행에 따라 구성됩니다.

-   `cmd/`: 각 람다 함수의 `main` 패키지를 포함합니다 (예: `cmd/authorizer`, `cmd/performReading`).
-   `internal/`: 공유 비즈니스 로직, 데이터 모델 및 서비스 통합을 포함합니다.
-   `pkg/`: 공유 유틸리티 코드를 포함합니다.

### 초기 설정

1.  Go 모듈 초기화 (아직 하지 않은 경우):
    ```bash
    go mod init tarot-backend
    ```
2.  의존성 추가 시 설치:
    ```bash
    go get -u github.com/aws/aws-lambda-go
    ```

## 🚀 배포

이 서버리스 애플리케이션의 배포는 **AWS SAM (Serverless Application Model)**을 통해 관리됩니다. `template.yaml` 파일이 필요한 모든 AWS 리소스(API Gateway, 람다 함수, IAM 역할 등)를 정의하여 자동화되고 반복 가능한 배포를 가능하게 합니다.
