# Keycloak 기반 전화번호 & PIN 공통 인증 시스템 (Web UI & CLI)

이 프로젝트는 Keycloak 서버를 연동하여 **휴대폰 번호, 이름, 이메일, 단방향 해싱(bcrypt)된 PIN 번호**를 기반으로 유저를 관리하고 인증하는 **통합 인증 프록시 시스템 및 웹 UI 서비스**입니다.

FastAPI와 Jinja2 템플릿 엔진을 활용하여 구축되었으며, 로컬 개발/테스트 시 방화벽이나 공유기 제약(NAT) 때문에 외부 OIDC 콜백을 수신하지 못하는 문제를 **백엔드 프록시(Back-end Proxy) 아키텍처**를 통해 근본적으로 극복하였습니다.

---

## 🛠️ 아키텍처 및 핵심 해결 과제

1. **로컬 NAT 콜백 불필요 (Back-end Proxy 방식)**
   - 브라우저를 Keycloak 기본 로그인 창으로 리다이렉트(Standard Flow)하는 대신, 자체 UI(Jinja2)에서 휴대폰 번호와 PIN을 수집하고 백엔드(FastAPI)가 Keycloak Admin API로 아웃바운드 REST 통신을 통해 데이터 싱크 및 검증을 완료합니다. 
   - 이로 인해 로컬 개발 시 복잡한 ngrok 포트포워딩이나 인바운드 Callback 리다이렉트 URL 설정 없이 즉시 동작합니다.

2. **무만료 오프라인 토큰 적용 (Passwordless 연동)**
   - `.env`에 평문 어드민 비밀번호를 노출하지 않고 안전하게 삭제하기 위해 **오프라인 리프레시 토큰(Offline Refresh Token)** 기술(`scope=offline_access`)을 도입했습니다.
   - 최초 1회만 비밀번호를 입력해 반영구 토큰을 획득하면, 이후 CLI나 웹 서비스 구동 시 런타임에 만료된 토큰을 스스로 Keycloak과 교환하여 갱신(Self-Healing)합니다. 401 만료 에러가 영구히 방지됩니다.

3. **Keycloak 선언적 유저 프로필 자동 구성**
   - Keycloak Target Realm(`holyseeds`)의 declarative user profile 제약에 대응하여, 커스텀 속성(`phoneNumber`, `pinNumber`, `manager`)을 Keycloak REST API로 스키마에 자동 등록하는 셋업 모듈을 내장했습니다.

4. **3단계 권한 분리 및 사용자 통제 (3-Tier Role Hierarchy: User 0 / Admin 1 / Super 2)**
   - **일반 회원 (Flag = "0")**: 본인 프로필 관리 및 암호(PIN 번호) 변경 기능, 일반 서브 서비스 이용.
   - **일반 관리자 (Flag = "1")**: 독립 서브 서비스(Booking, Bus 등)의 관리자 기능 수행 (단, 사용자 권한 관리 기능은 접근 불가).
   - **최고 관리자 (Super Admin, Flag = "2")**: 중앙 사용자 권한 관리(User CRUD: `/auth/users`), 사용자별 권한 등급(0/1/2) 부여 및 박탈, 회원 탈퇴(삭제) 전용.
   - 최상위 개발용 번호(`01055787363`)는 부트스트랩 Super 계정으로 보호되며 락아웃(Lock-out)을 방지합니다.

---

## 📁 주요 프로젝트 구성 파일

- 🔑 **`keycloak_api.py`**: 자가 갱신 토큰 메커니즘, 3단계 권한 플래그 판정, PIN 검증 및 해싱 변경 로직을 내장한 Keycloak REST API 래퍼.
- 🛣️ **`routes.py`**: `/auth` prefix 하위 엔드포인트 세션 제어 및 Jinja2 템플릿 제어 레이어. 프로필 PIN 변경 검증, Super 전용 사용자 관리 라우트 등을 담당합니다.
- 🚀 **`main.py`**: ASGI 웹 애플리케이션 엔트리 포인트. 루트 경로(`/`) 접속 시 `/auth/login`으로의 리다이렉션을 관장합니다.
- 🔐 **`generate_admin_token.py`**: 어드민 로그인 후 오프라인 만료 없는 토큰을 생성해 `.env`를 업데이트하고 비밀번호를 파일에서 파기하는 보안 스크립트.
- 📋 **`configure_keycloak_schema.py`**: `holyseeds` Realm에 커스텀 속성(`phoneNumber`, `pinNumber`, `manager`)들을 API로 자동 생성 및 허용하는 스키마 구성 도구.
- 💻 **`keycloak_auth_cli.py`**: CLI 상에서 회원가입 -> 유저 조회 -> PIN 검증 -> 수정 -> 삭제 순서의 전체 가이드라인 흐름을 단독 E2E로 테스트하는 시나리오 검증기.
- 🖼️ **`templates/`** (Jinja2 HTML 화면 구성):
  - `login.html`: 깔끔하고 심플한 전화번호 기반 로그인 인터페이스 (비밀번호 토글 버튼 지원).
  - `signup.html`: 신규 계정을 간편하게 등록하는 사용자 가입 인터페이스 (비밀번호 토글 버튼 지원).
  - `profile.html`: 로그인 성공 시 마주하는 내 프로필 페이지. (권한 등급 뱃지 표시, **현재 PIN / 새 PIN / 새 PIN 확인 입력 검증 컨트롤**, Super일 때만 대시보드 링크 오픈).
  - `users.html`: Super(2) 권한 전용 사용자 관리 Cockpit (0=일반, 1=관리자, 2=슈퍼 드롭다운 변경 및 삭제 제어).

---

## 🚀 구동 및 연동 가이드

### 1단계: 환경 변수 설정
프로젝트 루트 폴더 내의 `.env` 파일에 접속 정보를 세팅합니다:
```env
KEYCLOAK_BASE_URL=https://auth.********.???
KEYCLOAK_REALM=master
KEYCLOAK_TARGET_REALM=holyseeds

# Master Admin 계정 설정 (최초 실행용)
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=-------  # 최초 실행 후 자동으로 삭제됩니다
KEYCLOAK_ADMIN_TOKEN=
```

### 2단계: 무만료 토큰 생성 및 패스워드 파기
아래 명령어를 기동해 어드민 권한을 담은 반영구 오프라인 토큰을 `.env`에 구속시키고 비밀번호를 파일에서 삭제합니다:
```bash
python generate_admin_token.py
```
*참고: 만약 `.env`에 패스워드가 이미 삭제된 상태에서 토큰을 재발행하고 싶다면, 실행 시 마스킹 콘솔 프롬프트로 비밀번호를 안전하게 입력할 수 있습니다.*

### 3단계: Keycloak 커스텀 프로필 스키마 구성
Keycloak의 유저 속성 필터링을 무력화하기 위해 커스텀 변수들을 스키마에 자동 빌드합니다:
```bash
python configure_keycloak_schema.py
```

### 4단계: CLI 단독 연동 검증
CLI 시나리오 테스터를 통해 Keycloak이 정상적으로 데이터를 연산하고 PIN BCrypt 해시 일치를 판정하는지 E2E 검증합니다:
```bash
python keycloak_auth_cli.py
```

### 5단계: 공통 웹 UI 서비스 구동
FastAPI 통합 인증 서버를 로컬 머신에서 구동합니다:
```bash
python main.py
```
서버 가동 후, 브라우저에서 아래 주소들을 통해 즉시 시뮬레이션할 수 있습니다:
- **인증 메인 게이트웨이**: [http://localhost:8000/](http://localhost:8000/) (방문 시 `/auth/login` 자동 리다이렉션)
- **신규 가입**: [http://localhost:8000/auth/signup](http://localhost:8000/auth/signup)
- **사용자 권한 관리 대시보드**: [http://localhost:8000/auth/users](http://localhost:8000/auth/users) *(관리자 로그인 시에만 인가)*

---

## 💡 기술 연동 트러블슈팅 및 핫픽스 기록

1. **Cloudflare integrity Check (Error 1010) 우회**:
   - 파이썬 기본 urllib 에이전트 요청이 외부 CDN에 의해 차단되는 문제를 브라우저 standard `User-Agent` 조작을 통해 극복하였습니다.
2. **Starlette 0.28+ TemplateResponseTypeError 대응**:
   - 최신 FastAPI 환경에서 Starlette의 템플릿 응답 인자 순서 변경 때문에 캐시 키 해싱 과정에서 딕셔너리가 유입되어 터지는 `TypeError: unhashable type: 'dict'` 문제를 시그니처 표준 리팩토링(`TemplateResponse(request, "name.html", context)`)으로 완벽 차단하였습니다.
3. **사용자 관리자 변경 시 실시간 반영**:
   - Keycloak attributes의 다중 값 배열 형태 처리(`attributes: {"manager": ["1"]}`)를 매핑하여 스키마 정밀도를 높였습니다.
