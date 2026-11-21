# 통합 요구사항 누적 기록 (notes/requirement.md)

본 문서는 프로젝트의 초기 요구사항부터 현재까지의 모든 개발 요구사항을 시간순으로 누적하여 기록 및 관리하는 마스터 문서입니다.

---

## [1단계] 초기 요구사항: Keycloak 기반 사용자 관리 및 인증 시스템 CLI 샘플 프로그램 (기존 `requirements.md` 통합)

### 1. 시스템 환경 및 접속 정보
* **Application Domain**: `https://holyseeds.thewayworks.net`
* **Auth UI / Service**: `https://holyseeds.thewayworks.net/auth` (회원가입, 로그인, 프로필 변경)
* **Keycloak Server Domain**: `https://auth.thewayworks.net`
* **Admin/System Realm**: `master` (`KEYCLOAK_REALM`)
* **Target Application Realm**: `holyseeds` (`KEYCLOAK_TARGET_REALM`)
* **Client Type**: Confidential Client (Backend CLI 및 Service-to-Service 통신용)

### 2. Keycloak 사전 설정 및 커스텀 속성
* Target Realm (`holyseeds`) 커스텀 속성(User Attributes):
  * `phoneNumber`: 휴대폰 번호 (예: `01055787363`)
  * `pinNumber`: bcrypt/SHA-256 등으로 단방향 해싱(Hashing) 처리되어 저장될 PIN 번호
* 무만료 Offline Refresh Token(`scope=offline_access`)을 발급하여 `.env`의 평문 패스워드를 파기하고 런타임 자동 갱신(Self-Healing) 구조 구축.
* Declarative User Profile 스키마에 커스텀 속성 자동 등록(`configure_keycloak_schema.py`).

### 3. CLI 테스트 시나리오
1. `step1_get_admin_token()`: 토큰 획득 및 동적 갱신
2. `step2_signup_user()`: 휴대폰 번호, 이름, 이메일, 해싱된 PIN으로 사용자 생성
3. `step3_search_user_by_phone()`: 휴대폰 번호 기반 사용자 및 속성 조회
4. `step4_login_verify_pin()`: 입력 PIN과 저장된 해시 비교 검증
5. `step5_update_profile()`: 이름/이메일 등 프로필 정보 수정
6. `step6_cleanup_test_user()`: 테스트 유저 삭제

---

## [2단계] 웹 UI 공통 인증 서비스 및 3단계 관리자 권한 체계 (기존 `plan-web.md` & `history.md` 통합)

1. **Back-end Proxy 방식 웹 UI (`/auth` 하위 라우팅)**:
   * NAT/방화벽 환경에서도 OIDC 인바운드 콜백 없이 동작하도록 FastAPI + Jinja2 기반 자체 폼에서 자격 증명(전화번호, PIN)을 수집하고 백엔드가 Keycloak Admin API와 아웃바운드 통신.
   * 주요 엔드포인트: `/auth/login`, `/auth/signup`, `/auth/profile`, `/auth/users`, `/auth/logout`, `/auth/api/verify-session`.
2. **내 프로필 관리 내 암호(PIN 번호) 변경 기능**:
   * 현재 PIN 번호 검증, 새 PIN 번호 및 새 PIN 확인 일치 검증(최소 4자리), 비밀번호 표시/숨기기(👁️) 토글 지원.
3. **3단계 관리자 등급(`manager` flag: 0 ~ 2) 분리**:
   * `0`: 일반 회원 (`user`) - 내 프로필 관리 및 일반 서비스 이용.
   * `1`: 일반 관리자 (`admin` / `manager`) - 서브 서비스(Booking, Bus 등)의 관리자 기능 수행 (단, 사용자 권한 관리 CRUD 접근 불가).
   * `2`: 최고 관리자 (`super`) - 중앙 사용자 권한 관리(`/auth/users`), 권한 등급 부여/회수, 회원 삭제 전용.
   * 부트스트랩 계정(`01055787363`)은 상시 Super(`2`) 권한으로 자동 보호.

---

## [3단계] 2026-11-21 추가 요구사항 (문서 관리 규칙 제정, Developer 등급 체계, 로컬 개발용 외부 인증 검증 예외 API 및 보안 가이드)

### 1. 문서 및 산출물 기록 유지 규칙
* 모든 코드 개발이나 처리 요청사항은 아래 규칙에 따라 `notes/` 디렉토리에 기록을 유지해야 함:
  1. **계획 수립**: 요구사항 지시 시 첫째로 계획을 수립하여 `notes/plan_YYYYMMDDHHmm.md`에 기록.
  2. **개발 이력 요약**: 매번 개발 요구사항과 요약은 `notes/history.md`에 기록.
  3. **원본 요구사항 및 계획**: 사용자 원본 요구사항과 계획 기록은 `notes/req_YYYYMMDDHHmm.md`에 기록.
  4. **산출물 생성 기록**: 산출물 생성 및 변경 결과 기록은 `notes/result_YYYYMMDDHHmm.md`에 항상 기록.
  5. **누적 요구사항**: 모든 요구사항은 누적하여 `notes/requirement.md`에 기록.
* 프로젝트의 목적, 사용법, 구현 기능 등에 대한 상세 설명은 루트의 `README.md`에 작성.
* 인증 절차 API 활용을 위한 API SPEC, 활용 샘플 등 구현 지원 가이드는 루트의 `auth_spec.md`에 유지하여 타 애플리케이션 개발 시 참조 가능하도록 지원.
* 기존 루트에 생성된 문서들(`requirements.md`, `plan.md`, `plan-web.md`, `history.md`)은 모두 `notes/` 아래로 이동하고 산출물 규칙에 따라 통합 구성.

### 2. 개발자 여부 및 등급 확인을 위한 `developer` Flag 필드 추가
* 기존 관리자 등급용 `manager` flag (`0`: 일반 user, `1`: admin, `2`: super) 외에 **개발자 여부와 등급을 확인하는 `developer` flag 필드**를 추가.
* **`developer` 등급 정의 (`0` ~ `2`)**:
  * `0`: 일반 `user` (비개발자)
  * `1`: 일반 `developer`
  * `2`: `dev-leader`
* 사용자 인증 절차(로그인, 프로필, 사용자 관리 대시보드 `/auth/users`, 세션 검증 API `/auth/api/verify-session`)에 `developer` 여부를 검증하고 관리하는 부분을 추가.
* 인증 시 그 flag 결과를 바탕으로 서브 애플리케이션에서 사용자 권한(관리자 등급 + 개발자 등급)에 따라 활용할 수 있도록 지원.

### 3. 로컬 개발 환경을 위한 외부 공개 인증앱 직접 호출(Direct Call / Callback 우회) 예외 API 및 보안 통제 가이드
* **배경 및 문제점**:
  * 로컬에서 서브 앱을 개발할 때, 외부에 배포된 중앙 인증 앱(예: `https://holyseeds.thewayworks.net/auth`)을 통해 인증을 수행한 뒤 로컬 콜백 주소(예: `http://localhost:5000`)로 리턴받아야 하는 시나리오나, 외부에서 로컬 콜백 주소로 접근할 수 없는 네트워크 환경(또는 도메인 불일치로 인한 브라우저 쿠키 미전달 환경)이 존재함.
  * 따라서 로컬 앱이 외부에 공개된 인증앱 URL로부터 인증 세션 정보를 그대로 받아서(또는 직접 자격 증명/세션 토큰으로) 공개 인증앱에 직접 Call을 하면 인증 Verification을 수행할 수 있도록 허용해야 함.
* **요구사항**:
  * 로컬 개발의 경우를 위한 **예외 인증/검증 API** ( 및 로컬 콜백 토큰 전달 메커니즘)를 설계 및 제작.
  * 로컬 개발 예외 API가 프로덕션 환경에서 악용되지 않도록 통제할 수 있는 **보안 가이드(개발자 등급 `developer >= 1` 검증 결합, 로컬호스트 Origin/Redirect 제한, 단기 일회용 토큰 또는 개발자 전용 API Key, Rate Limiting 등)**를 제안하고 문서화(`auth_spec.md`, `README.md`).
  * 개발 계획 수립과 개발 내역을 자세히 기술하여 안내한 뒤, 사용자 리뷰 후 실제 코드 개발을 진행.
