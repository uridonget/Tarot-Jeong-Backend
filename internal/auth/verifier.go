package auth

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/golang-jwt/jwt/v5"
)

// claims는 Supabase가 발행하는 JWT의 payload 구조를 나타냅니다.
// 필요한 정보(email, sub)를 파싱하기 위해 사용됩니다.
type claims struct {
	jwt.RegisteredClaims
	Email    string `json:"email"`
	UserUID  string `json:"sub"` // Supabase는 사용자 고유 ID를 "sub" 클레임에 담습니다.
	UserRole string `json:"role"`
}

var (
	// 한 번 가져온 JWT 시크릿을 캐싱하여, Lambda가 재실행될 때마다 Parameter Store를 호출하는 것을 방지합니다.
	jwtSecret string
	// 동시성 문제 방지를 위한 뮤텍스
	secretMux sync.Mutex
	// SSM 클라이언트 인스턴스
	ssmClient *ssm.Client
	// JWT 시크릿이 저장된 AWS Systems Manager Parameter Store의 경로입니다.
	// 이 값은 Lambda 함수의 환경 변수 'JWT_SECRET_PARAM_PATH'를 통해 주입되어야 합니다.
	jwtSecretParamPath = os.Getenv("JWT_SECRET_PARAM_PATH")
)

// getSSMClient는 AWS SSM 클라이언트를 초기화하고 반환합니다.
// 싱글톤 패턴을 사용하여, 한 번 생성된 클라이언트를 계속 재사용합니다.
func getSSMClient(ctx context.Context) (*ssm.Client, error) {
	if ssmClient == nil {
		cfg, err := config.LoadDefaultAWSConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("AWS 설정 로딩 실패: %w", err)
		}
		ssmClient = ssm.NewFromConfig(cfg)
	}
	return ssmClient, nil
}

// getJWTSecret는 AWS Systems Manager Parameter Store에서 JWT 시크릿을 가져옵니다.
// 가져온 시크릿은 전역 변수 'jwtSecret'에 캐싱하여 불필요한 API 호출을 줄입니다.
func getJWTSecret(ctx context.Context) (string, error) {
	// 여러 요청이 동시에 시크릿을 가져오려 할 때의 경쟁 상태를 방지합니다.
	secretMux.Lock()
	defer secretMux.Unlock()

	// 시크릿이 이미 캐시되어 있다면, 즉시 반환합니다.
	if jwtSecret != "" {
		return jwtSecret, nil
	}

	// 환경변수가 설정되지 않았다면 에러를 반환합니다.
	if jwtSecretParamPath == "" {
		return "", errors.New("JWT_SECRET_PARAM_PATH 환경 변수가 설정되지 않았습니다")
	}

	client, err := getSSMClient(ctx)
	if err != nil {
		return "", fmt.Errorf("SSM 클라이언트 생성 실패: %w", err)
	}

	// Parameter Store에서 SecureString 타입의 파라미터를 가져옵니다.
	paramOutput, err := client.GetParameter(ctx, &ssm.GetParameterInput{
		Name:           &jwtSecretParamPath,
		WithDecryption: true, // SecureString을 복호화하기 위해 true로 설정
	})
	if err != nil {
		return "", fmt.Errorf("Parameter Store에서 JWT 시크릿을 가져오는 데 실패했습니다: %w", err)
	}

	if paramOutput.Parameter == nil || paramOutput.Parameter.Value == nil {
		return "", errors.New("JWT 시크릿 파라미터 값이 존재하지 않습니다")
	}

	// 가져온 시크릿을 전역 변수에 캐싱합니다.
	jwtSecret = *paramOutput.Parameter.Value
	return jwtSecret, nil
}

// VerifyToken은 전달된 JWT 문자열을 검증하고, 유효한 경우 사용자의 고유 ID (sub 클레임)를 반환합니다.
func VerifyToken(ctx context.Context, tokenString string) (string, error) {
	if tokenString == "" {
		return "", errors.New("인증 토큰이 없습니다")
	}

	// "Bearer " 접두사가 있는 경우 제거합니다.
	if strings.HasPrefix(tokenString, "Bearer ") {
		tokenString = strings.TrimPrefix(tokenString, "Bearer ")
	}

	// Parameter Store에서 JWT 시크릿을 가져옵니다. (내부적으로 캐싱 처리됨)
	secret, err := getJWTSecret(ctx)
	if err != nil {
		log.Printf("JWT 시크릿을 가져오는 중 에러 발생: %v", err)
		return "", errors.New("토큰 검증 중 내부 서버 오류 발생")
	}

	// JWT 파싱 및 검증
	token, err := jwt.ParseWithClaims(tokenString, &claims{}, func(token *jwt.Token) (interface{}, error) {
		// 서명 알고리즘이 HMAC인지 확인합니다. (Supabase 기본값)
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("예상치 못한 서명 알고리즘: %v", token.Header["alg"])
		}
		// 검증에 사용할 시크릿 키를 바이트 슬라이스 형태로 반환합니다.
		return []byte(secret), nil
	}, jwt.WithLeeway(5*time.Second)) // 약간의 시간 오차(skew)를 허용합니다.

	if err != nil {
		log.Printf("토큰 파싱/검증 실패: %v", err)
		return "", fmt.Errorf("유효하지 않은 토큰: %w", err)
	}

	// 토큰이 유효하지 않은 경우 에러를 반환합니다.
	if !token.Valid {
		return "", errors.New("유효하지 않은 토큰")
	}

	// 토큰의 클레임(payload)을 파싱합니다.
	claims, ok := token.Claims.(*claims)
	if !ok || claims.UserUID == "" {
		return "", errors.New("유효하지 않은 토큰 클레임 또는 사용자 ID 없음")
	}

	// 클레임에서 사용자 ID를 추출하여 반환합니다.
	return claims.UserUID, nil
}
