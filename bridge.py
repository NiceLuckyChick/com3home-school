import sys
import json
from pycomcigan import TimeTable, get_school_code

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "인자가 부족합니다."}))
        return

    mode = sys.argv[1]

    # 1. 학교 검색 모드
    if mode == "search":
        query = sys.argv[2]
        try:
            schools = get_school_code(query)
            # schools: [[지역, 학교명, 학교코드, 지역코드], ...]
            result = []
            for s in schools:
                result.append({
                    "region": s[0],
                    "name": s[1],
                    "comciganCode": s[2]
                })
            print(json.dumps({"list": result}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"error": str(e), "list": []}, ensure_ascii=False))

    # 2. 주간 시간표 조회 모드
    elif mode == "timetable":
        school_name = sys.argv[2]
        grade = int(sys.argv[3])
        class_num = int(sys.argv[4])

        try:
            # 이번 주(week_num=0) 시간표 가져오기
            tt = TimeTable(school_name, week_num=0)
            
            # pycomcigan 시간표 구조: tt.timetable[학년][반][요일(0=월~4=금)][교시]
            class_schedule = tt.timetable[grade][class_num]
            
            week_data = []
            for day_idx, day_periods in enumerate(class_schedule):
                day_list = []
                for p_idx, subject in enumerate(day_periods):
                    if subject and subject.strip():
                        day_list.append({
                            "period": p_idx + 1,
                            "subject": subject.strip(),
                            "teacher": "", # pycomcigan 과목 문자열 매핑
                            "changed": False
                        })
                    else:
                        day_list.append({
                            "period": p_idx + 1,
                            "subject": "수업 없음",
                            "teacher": "",
                            "changed": False
                        })
                week_data.append(day_list)

            print(json.dumps({"data": week_data}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))

if __name__ == "__main__":
    main()