# 설계

## 현재 상태

Python 3.12 단일 패키지와 두 개의 GitHub Actions 수동 워크플로로 MVP가 구현되어 있다. 외부 자격증명 없이 실행되는 자동 테스트까지 완료됐으며, 실제 노션·OpenAI·GitHub 연동 검증만 환경 제공 전까지 남아 있다. 제품 범위는 `01_프로그램기능.md`, 결정과 가정은 `docs/DECISIONS.md`를 기준으로 한다.

## 구조

```text
.
├── .github/workflows/
│   ├── sync-notion.yml       # session별 노션 동기화와 커밋
│   └── generate-quiz.yml     # session별 퀴즈 생성과 커밋
├── src/study_quiz/
│   ├── __main__.py           # sync/generate CLI와 종료 코드
│   ├── config.py             # 환경변수와 session 입력 검증
│   ├── http.py               # JSON HTTP 전송과 재시도
│   ├── notion.py             # 데이터 소스 조회와 블록 변환
│   ├── sync.py               # 충돌 감지와 session 원자적 교체
│   ├── quiz.py               # 글 수집, AI 요청·검증, 출력
│   ├── summary.py            # 콘솔과 Actions summary 보고
│   ├── models.py
│   └── errors.py
├── tests/                    # 외부 API를 대체한 단위·통합 테스트
├── tools/
│   ├── check_repo.py         # 의존성 없는 정적·워크플로 검사
│   └── commit_session.sh     # 변경이 있을 때만 제한된 파일 커밋
├── Makefile
└── pyproject.toml
```

설치 후 로컬과 워크플로는 같은 진입점을 사용한다.

```text
python -m study_quiz sync --session <번호>
python -m study_quiz generate --session <번호>
```

session 번호는 1~9999의 정수로 검증하고 두 자리 이상으로 맞춰 `session01`, `session02`처럼 경로를 만든다. 운영 설정과 실행 방법은 `README.md`에 있다.

## 핵심 데이터 흐름

### 노션 동기화

1. `sync-notion.yml`이 수동 입력 session을 검증한다.
2. 노션 database에서 데이터 소스 ID를 찾는다. 데이터 소스가 여러 개면 `NOTION_DATA_SOURCE_ID`를 요구한다.
3. 데이터 소스 스키마를 읽고 실제 속성 형식에 맞춰 게시 상태와 Session filter를 만든다. 목록과 각 페이지 블록은 끝까지 pagination한다.
4. 제목과 지원하는 텍스트 블록을 Markdown으로 변환한다. 외부 파일은 원본 URL, 노션 내부 파일은 만료 가능한 다운로드 URL 대신 원본 페이지 링크를 기록한다.
5. 노션 페이지 ID로 기존 파일을 찾고 `sync_hash`로 사용자 수정 여부를 확인한다.
6. 모든 페이지를 변환·검증한 뒤 session 디렉터리의 임시 복제본에 결과를 만든다. 검증된 복제본만 기존 디렉터리와 교체한다.
7. 워크플로는 실제 diff가 있을 때만 해당 session을 한 번 커밋하고 push한다.

동기화 파일의 front matter에는 `notion_page_id`, `notion_url`, `notion_last_edited_time`, `title`, `sync_hash`가 있다. 파일명은 정규화한 제목과 짧은 페이지 ID의 조합이다. 제목이 바뀌면 같은 페이지 ID의 이전 파일을 새 이름으로 옮긴다. 이번 조회에서 사라진 기존 글은 삭제하지 않는다.

### 퀴즈 생성

1. `generate-quiz.yml`이 수동 입력 session을 검증한다.
2. 지정한 `sessionNN/`에서 `quiz.md`와 `quiz_answers.md`를 제외한 Markdown 글을 읽는다.
3. 글은 지시가 아닌 근거 데이터로 구분해 OpenAI Responses API에 전달한다. 요청의 `text.format`에 strict JSON Schema를 사용해 최대 20개의 4지선다 문제를 받는다.
4. 응답 JSON을 다시 검사하여 문제 수, 보기 4개와 중복 여부, 정답 범위, 해설, 실제 존재하는 근거 파일을 확인한다. 유효한 문제가 0개이면 실패한다.
5. 전체 검증 후 `quiz.md`와 `quiz_answers.md`를 session 임시 복제본에서 함께 교체한다.
6. 워크플로는 실제 diff가 있을 때만 두 출력 파일을 한 번 커밋하고 push한다.

## 상태와 외부 인터페이스

별도 애플리케이션 DB는 사용하지 않는다.

| 상태 | 위치 | 역할 |
|---|---|---|
| 원본 글 | 노션 데이터 소스 | 팀원이 작성하는 원본 |
| 동기화 글 | `sessionNN/*.md` | 퀴즈 입력 및 변경 감지 정보 |
| 문제 | `sessionNN/quiz.md` | 진행자·참가자가 보는 문제 |
| 정답 | `sessionNN/quiz_answers.md` | 정답, 해설, 근거 링크 |
| 실행 기록 | Git 이력과 Actions 로그/요약 | 성공 커밋과 실패 원인 확인 |

노션은 `Notion-Version: 2025-09-03`의 database/data source/blocks API를 사용한다. AI 기본 구현은 OpenAI Responses API의 JSON Schema 구조화 출력이며 모델명은 `OPENAI_MODEL`로만 정한다. 두 API 모두 표준 라이브러리 HTTP 전송 경계 뒤에 있어 테스트에서는 가짜 전송기로 교체된다.

## 오류 처리

- 필수 설정 누락과 잘못된 session은 외부 호출 전에 non-zero로 종료한다.
- 대상 노션 글이 없거나 퀴즈 입력 글이 없으면 기존 파일을 변경하지 않고 실패한다.
- HTTP 429, timeout, 5xx만 지수 지연으로 최대 2회 재시도한다. 인증과 잘못된 요청은 즉시 실패한다.
- 불완전한 pagination, 지원하지 않는 노션 블록, 잘못된 AI 응답은 대상 ID를 포함해 실패한다. AI 형식 오류는 최대 2회 다시 생성한다.
- 동기화된 파일 내용과 `sync_hash`가 다르면 사용자 수정 충돌로 처리한다.
- 파일은 같은 저장소 안의 임시 session 디렉터리에서 준비하고, 검증 완료 후 디렉터리 단위로 교체한다. 실패 전에 기존 결과를 유지한다.
- CLI는 비밀값을 제외한 단계·대상 오류를 stderr와 `GITHUB_STEP_SUMMARY`에 기록한다.
- 두 워크플로는 같은 ref의 실행을 하나의 concurrency group으로 직렬화한다. 생성 명령이 성공해야 커밋 단계가 실행된다.

