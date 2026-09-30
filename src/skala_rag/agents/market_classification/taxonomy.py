"""The ten embodiment categories in the project design, section 2.3."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FormCategory:
    label: str
    priority_metrics: tuple[str, ...]


FORMS: dict[str, FormCategory] = {
    "fixed_manipulator": FormCategory("고정형 매니퓰레이터", ("가반하중", "반복정밀도", "사이클 타임")),
    "mobile_robot": FormCategory("이동형 로봇", ("주행 성공률", "운영시간", "관제 대수")),
    "mobile_manipulator": FormCategory("모바일 매니퓰레이터", ("이동·조작 통합 성공률",)),
    "humanoid": FormCategory("휴머노이드", ("자유도", "가반하중", "보행·균형 검증")),
    "legged_robot": FormCategory("다족보행 로봇", ("지형 통과율", "연속 운용시간")),
    "drone": FormCategory("드론·비행 로봇", ("비행시간", "자율비행 수준", "인증")),
    "marine_robot": FormCategory("해양·수중 로봇", ("운용 수심·시간", "통신 방식")),
    "wearable_exoskeleton": FormCategory("웨어러블·외골격", ("의료기기 인허가", "임상 결과")),
    "autonomous_vehicle": FormCategory("자율주행 차량", ("자율주행 레벨", "누적 주행거리")),
    "smart_space": FormCategory("스마트 공간·고정형 시스템", ("인식 정확도", "설치 현장 수")),
}

