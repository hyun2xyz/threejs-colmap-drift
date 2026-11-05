# OBS 종료 직후 잘못된 공간 부족 경고

이번 Windows 작업에서 디스크 여유가100GB 이상인데도 녹화 종료 시 공간 부족 경고가 반복됐습니다. 로그 순서는 다음과 같았습니다.

1. 자동화가 `StopRecord` 요청의 응답을 받음.
2. 녹화 출력이 완전히 닫히기 전에 이전 프로필로 복귀.
3. 이전 프로필의 녹화 폴더가 존재하지 않아 Windows 공간 조회가 `ERROR_PATH_NOT_FOUND (3)`으로 실패.
4. OBS 공간 부족 메시지가 표시된 뒤 muxer 종료 로그가 기록됨.

해결은 디스크 정리가 아니라 **기존 프로필의 유효한 저장 폴더 복구 + 녹화 종료 확인 후 프로필 복귀**였습니다. 프로젝트 안의폴더만 복구했고 기존 미디어는 삭제하지 않았습니다. 짧은 실제 녹화→파일 잠금 해제→프로필 복귀 회귀검사에서 추가 경고0회, 파일 전체 디코딩을 확인했습니다. 모든 공간 부족 경고가 같은 원인이라는 뜻은 아닙니다.

재사용 가능한 방어 코드는 [tools/obs_safe_stop.py](../tools/obs_safe_stop.py)에 있습니다. 본인의 인증된 로컬 OBS 어댑터를 `request` 함수로 넘깁니다. 비밀번호나 설치별 설정 파일은 저장소에 포함하지 않습니다.

```python
from tools.obs_safe_stop import ensure_record_directory, stop_record_safely

# 본인 어댑터: request(method, data=None) -> responseData
ensure_record_directory(record_directory)
receipt = stop_record_safely(request)
# 위 함수가 성공한 후에만 SetCurrentProfile/SetCurrentSceneCollection을 호출
```

또한 Windows 고DPI 창 캡처에서는 실제 소스 크기가 OBS 캔버스보다 클 수 있습니다. 소스의 실제 화면을 확인하고 장면 항목의 bounds를 캔버스에 맞춰야 합니다. MP4가 끝까지 디코딩된다는 사실만으로 창 전체가 녹화됐다고 판단하면 안 됩니다.
