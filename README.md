# 타로정 (Tarot-Jeong) - 백엔드

본 프로젝트는 '타로정' 웹 애플리케이션의 백엔드 서버입니다. AWS의 서버리스 기술을 기반으로 구축되어 확장성과 유지보수성을 높였으며, 사용자의 고민에 대한 타로점 해석을 Google Gemini API를 통해 제공합니다.

## 🏛️ 아키텍처 개요

이 백엔드는 AWS SAM (Serverless Application Model)을 사용하여 파이썬으로 작성된 서버리스 애플리케이션입니다. 주요 구성 요소는 다음과 같습니다.

- **API Gateway**: 클라이언트 요청을 받아 적절한 Lambda 함수로 라우팅하는 HTTP API 엔드포인트를 제공합니다. CORS가 설정되어 지정된 프론트엔드 도메인에서의 요청을 처리합니다.
- **AWS Lambda**: 각 기능을 수행하는 파이썬 코드의 실행 환경입니다. 각 함수는 독립적인 디렉터리에서 관리됩니다.
- **AWS SSM Parameter Store**: 데이터베이스 연결 문자열, API 키 등 민감한 구성 정보를 안전하게 저장하고 Lambda 함수에서 참조합니다.
- **Supabase**: 사용자 인증(JWT) 및 데이터베이스(Postgres)를 위해 사용되는 외부 서비스입니다.

## ✨ 주요 기능 및 API 엔드포인트

| Method | Path                  | 인증   | 설명                                                                           |
| :----- | :-------------------- | :--- | :----------------------------------------------------------------------------- |
| `GET`    | `/profile`            | 필요   | 사용자의 프로필 정보를 조회합니다. DB에 없으면 Supabase 인증 정보 기반으로 자동 생성합니다. |
| `POST`   | `/tarot-reading`      | 필요   | 사용자의 고민과 선택된 카드를 받아 Gemini API로 타로점 해석을 요청하고 결과를 반환합니다. |
| `POST`   | `/share`              | 필요   | 타로점 결과를 DB에 저장하고, 다른 사람이 볼 수 있는 고유한 공유 ID를 생성합니다.       |
| `GET`    | `/share/{share_id}` | 불필요 | 공유 ID에 해당하는 타로점 결과를 조회하여 반환합니다. (공개 접근)                 |

### 요구사항

- [AWS CLI](https://aws.amazon.com/cli/): AWS 리소스를 관리하기 위한 커맨드 라인 인터페이스
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html): 서버리스 애플리케이션을 빌드하고 배포하기 위한 도구
- [Python 3.12](https://www.python.org/): Lambda 함수 실행 환경
- [Docker](https://www.docker.com/): SAM CLI가 의존성을 빌드할 때 사용하는 컨테이너 환경

## 🚀 배포

1.  **의존성 빌드**

    SAM 애플리케이션을 빌드합니다. 이 과정에서 각 Lambda 함수 폴더의 `requirements.txt` 파일을 읽어 필요한 라이브러리를 설치하고 배포 가능한 아티팩트를 생성합니다.
    ```bash
    # Backend 디렉터리 내에서 실행
    sam build
    ```

2.  **배포**

    빌드된 애플리케이션을 AWS 클라우드에 배포합니다. 최초 배포 시에는 `--guided` 플래그를 사용하여 스택 이름, 리전, 파라미터 값 등을 대화형으로 설정하는 것이 편리합니다.
    ```bash
    # 최초 배포 시
    sam deploy --guided

    # 이후 배포 시 (samconfig.toml 파일이 생성된 후)
    sam deploy
    ```
    배포가 완료되면 `Outputs` 섹션에 API Gateway의 엔드포인트 URL이 출력됩니다.