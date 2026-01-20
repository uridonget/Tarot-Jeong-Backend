package main

import (
	"context"
	"fmt"
	"log"
	"strings"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"

	"tarot-backend/internal/auth" // 우리가 작성한 internal/auth 패키지를 임포트합니다.
)

// handler 함수는 AWS Lambda에 의해 직접 호출되는 메인 로직입니다.
// API Gateway Custom Authorizer(REQUEST 타입) 이벤트가 발생할 때마다 실행됩니다.
func handler(ctx context.Context, event events.APIGatewayCustomAuthorizerRequest) (events.APIGatewayCustomAuthorizerResponse, error) {
	// 어떤 요청이 들어왔는지 로그를 남깁니다. (디버깅에 유용)
	log.Printf("Authorizer 이벤트 수신: %+v", event)

	// 이벤트에서 Authorization 헤더 값을 가져옵니다.
	token := event.AuthorizationToken
	if token == "" {
		log.Println("Authorization 토큰이 없습니다.")
		// 토큰이 없으면 즉시 접근 거부(Deny) 정책을 반환합니다.
		return generatePolicy("user", events.IAMDeny, "*", "Anonymous"), fmt.Errorf("Unauthorized")
	}

	// 토큰에서 "Bearer " 접두사를 제거합니다.
	if strings.HasPrefix(token, "Bearer ") {
		token = strings.TrimPrefix(token, "Bearer ")
	}

	// internal/auth 패키지의 VerifyToken 함수를 호출하여 토큰을 검증합니다.
	userID, err := auth.VerifyToken(ctx, token)
	if err != nil {
		log.Printf("토큰 검증 실패: %v", err)
		// 검증에 실패하면 접근 거부(Deny) 정책을 반환합니다.
		return generatePolicy("user", events.IAMDeny, "*", "Anonymous"), fmt.Errorf("Unauthorized")
	}

	log.Printf("토큰이 성공적으로 검증되었습니다. 사용자 ID: %s", userID)

	// 검증에 성공하면, API Gateway에게 후속 Lambda 함수 호출을 허용(Allow)하는 IAM 정책을 반환합니다.
	// 이 때, `principalId`로 사용자 ID를 전달하고, `context` 맵에 추가 정보를 담아 후속 Lambda에서 사용할 수 있게 합니다.
	return generatePolicy(userID, events.IAMAllow, event.MethodArn, userID), nil
}

// generatePolicy는 API Gateway Authorizer가 요구하는 형식의 IAM 정책 응답을 생성합니다.
func generatePolicy(principalID, effect, resource, userID string) events.APIGatewayCustomAuthorizerResponse {
	// 응답의 기본 구조를 생성합니다. PrincipalID는 요청의 주체를 나타냅니다.
	authResponse := events.APIGatewayCustomAuthorizerResponse{PrincipalID: principalID}

	// effect와 resource가 유효한 경우, IAM 정책 문서를 생성합니다.
	if effect != "" && resource != "" {
		authResponse.PolicyDocument = events.APIGatewayCustomAuthorizerResponse_PolicyDocument{
			Version: "2012-10-17",
			Statement: []events.IAMPolicyStatement{
				{
					Action:   []string{"execute-api:Invoke"}, // API Gateway 실행 권한
					Effect:   effect,                         // "Allow" 또는 "Deny"
					Resource: []string{resource},             // 요청이 발생한 API의 ARN
				},
			},
		}
	}

	// 이 Authorizer를 통과한 후 호출될 Lambda 함수에게 전달할 추가 정보(컨텍스트)를 설정합니다.
	// 후속 Lambda에서는 `event.RequestContext.Authorizer["user_id"]` 형태로 이 값을 꺼내 쓸 수 있습니다.
	authResponse.Context = map[string]interface{}{
		"user_id": userID,
	}

	return authResponse
}

// main 함수는 Lambda 실행 환경의 시작점입니다.
// handler 함수를 Lambda 실행 루프에 등록합니다.
func main() {
	lambda.Start(handler)
}
