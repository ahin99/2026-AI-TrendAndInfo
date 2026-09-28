# Study Quiz

노션 데이터 소스의 게시 글을 `sessionNN/` Markdown으로 동기화하고, 해당 글만 근거로 4지선다 퀴즈를 생성하는 GitHub Actions 자동화다.

## GitHub 설정

이 폴더의 `.github/`와 `sessionNN/`이 GitHub 저장소 루트에 있어야 한다. 다른 저장소의 하위 폴더로 커밋하면 GitHub Actions가 이 workflow를 인식하지 않는다.

Repository secret을 등록한다.

- `NOTION_TOKEN`: 읽기 권한이 있고 대상 database가 공유된 노션 integration 토큰
- `NOTION_DATABASE_ID`: 대상 database ID
- `OPENAI_API_KEY`: Responses API를 호출할 API 키

Repository variable을 등록한다.

- `OPENAI_MODEL`: 구조화 출력을 지원하는 모델명. 의도하지 않은 모델 변경을 막기 위해 기본값은 없다.
- 선택: `OPENAI_API_BASE`. 기본값은 `https://api.openai.com/v1`이며 Responses API와 호환되는 endpoint만 사용할 수 있다.
- 선택: `NOTION_DATA_SOURCE_ID`. database에 데이터 소스가 여러 개일 때 필수다.
- 선택: `NOTION_NAME_PROPERTY`, `NOTION_SESSION_PROPERTY`, `NOTION_STATUS_PROPERTY`, `NOTION_PUBLISHED_VALUE`
- 선택: `NOTION_SESSION_VALUE_TEMPLATE`. 기본값은 `session{session:02d}`이며 session 1을 `session01`로 조회한다. Session 속성이 number 형식이면 입력 숫자를 그대로 조회한다.

노션의 기본 속성은 `Name`(title), `Session`(select/status/rich_text/number), `Status`(select/status/rich_text)다. 게시 상태 기본값은 `Published`다.

Actions의 **Sync Notion** 또는 **Generate Quiz**에서 `Run workflow`를 누르고 session 번호를 입력한다. 두 작업은 성공했고 실제 변경이 있을 때만 해당 session 파일을 커밋한다.

## 로컬 실행과 검증

Python 3.12 환경에서 저장소 루트를 기준으로 실행한다.

```bash
python -m pip install .
python -m study_quiz sync --session 1
python -m study_quiz generate --session 1
make test
make check
```

로컬 실행도 위와 같은 환경변수가 필요하다. 오류가 나면 일부 파일을 남기지 않으며, 동기화된 글을 직접 수정한 경우 덮어쓰지 않고 충돌로 종료한다.
