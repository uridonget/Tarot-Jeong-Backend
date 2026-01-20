package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
)

// Response는 API Gateway에 반환할 응답의 구조체입니다.
type Response events.APIGatewayProxyResponse

// handler 함수는 API Gateway로부터 요청을 받아 처리합니다.
// 이 함수는 Lambda Authorizer 뒤에서 실행되는 것을 전제로 합니다.
func handler(ctx context.Context, request events.APIGatewayProxyRequest) (Response, error) {
	// 어떤 요청이 들어왔는지 로그를 남깁니다.
	log.Printf("Request received: %+v", request)

	// Lambda Authorizer가 `context`에 담아준 사용자 ID를 추출합니다.
	// `request.RequestContext.Authorizer`는 map[string]interface{} 타입입니다.
	authorizerContext, ok := request.RequestContext.Authorizer.(map[string]interface{})
	if !ok {
		return response(401, `{"error":"Authorizer context is missing"}`), nil
	}

	userID, ok := authorizerContext["user_id"].(string)
	if !ok || userID == "" {
		return response(401, `{"error":"User ID not found in authorizer context"}`), nil
	}

	log.Printf("Successfully authenticated user ID: %s", userID)

	// (미래 확장)
	// 이 userID를 사용하여 Supabase DB에서 사용자의 프로필 정보(닉네임, 크레딧 등)를 조회할 수 있습니다.
	// profile, err := db.GetProfile(ctx, userID)
	// ...

	// 지금은 인증 성공 여부를 확인하기 위해 간단한 성공 메시지와 사용자 ID를 반환합니다.
	successMessage := fmt.Sprintf(`{"message":"Authentication successful", "user_id":"%s"}`, userID)

	return response(200, successMessage), nil
}

// response 함수는 HTTP 상태 코드와 응답 본문을 받아
// API Gateway가 요구하는 형식의 Response 구조체를 생성합니다.
func response(statusCode int, body string) Response {
	// CORS를 허용하기 위해 헤더를 설정합니다. (개발 환경에서는 "*"로 설정하고, 프로덕션에서는 특정 도메인으로 제한하는 것이 좋습니다.)
	headers := map[string]string{
		"Content-Type":                 "application/json",
		"Access-Control-Allow-Origin":  "*",
		"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
		"Access-Control-Allow-Headers": "Content-Type, Authorization",
	}

	// JSON 마샬링 예시 (현재는 문자열을 그대로 사용)
	// responseBody, _ := json.Marshal(map[string]string{"message": body})

	return Response{
		StatusCode:      statusCode,
		Headers:         headers,
		Body:            body,
		IsBase64Encoded: false,
	}
}

// main 함수는 Lambda 실행 환경의 시작점입니다.
func main() {
	lambda.Start(handler)
}
