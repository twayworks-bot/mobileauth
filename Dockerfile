# 1. Base Image 설정 (안정적이고 가벼운 Python 3.11-slim 사용)
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 환경 변수 기본값 등록 (.env 파일 참조하여 컨테이너 환경 변수로 노출)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KEYCLOAK_BASE_URL="https://auth.thewayworks.net" \
    KEYCLOAK_REALM="master" \
    KEYCLOAK_TARGET_REALM="holyseeds" \
    KEYCLOAK_ADMIN_USER="admin" \
    KEYCLOAK_CLIENT_ID="holyseeds-app-cli" \
    KEYCLOAK_CLIENT_SECRET="" \
    KEYCLOAK_ADMIN_TOKEN=""

# 4. 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 애플리케이션 소스 코드 및 템플릿 복사 (.dockerignore에서 불필요한 캐시/설정/OLD 폴더 자동 필터링)
COPY . .

# 6. 포트 노출 (Gunicorn 구동 포트인 5000번 노출)
EXPOSE 5000

# 7. 헬스체크 루틴 추가 (요청하신 조건 준수)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=5s \
    CMD python -c "import requests; requests.get('http://localhost:5000/auth/api/status')"

# 8. 컨테이너 기동 시 실 구동 커맨드 설정 (요청하신 Gunicorn 커맨드 준수)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--log-level", "debug", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "app:app"]
