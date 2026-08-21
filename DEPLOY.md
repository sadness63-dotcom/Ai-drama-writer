# 웹으로 배포하기

이 앱은 Streamlit 기반이라 PC에서 실행한 뒤 같은 네트워크에서 쓰거나, Streamlit Community Cloud / Render / Railway 같은 Python 웹 호스팅에 올려 브라우저에서 사용할 수 있습니다.

## API 키 보안

- API 키를 소스코드나 GitHub 저장소에 직접 넣지 마세요.
- 현재 앱은 실행 중 사이드바에 입력한 키를 사용하며 `project.json`에는 저장하지 않습니다.
- 공개 서버로 배포할 때는 로그인/접근제어를 추가하는 것을 권장합니다.

## Docker

```bash
docker build -t drama-writer-room .
docker run -p 8501:8501 drama-writer-room
```

브라우저에서 `http://localhost:8501`로 접속합니다.
