from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pycomcigan import TimeTable, get_school_code
import requests
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/search-school")
def search_school(name: str = Query(..., min_length=2)):
    try:
        schools = get_school_code(name.strip())
        comcigan_list = []
        
        # pycomcigan 1.4.3: [지역코드(0), 지역명(1), 학교명(2), 학교코드(3)]
        for s in schools:
            comcigan_list.append({
                "region": str(s[1]),      # 지역명
                "name": str(s[2]),        # 학교명
                "comciganCode": str(s[3]) # 컴시간 학교코드
            })

        # 나이스(NEIS) 학교 및 교육청 코드 검색
        neis_map = {}
        try:
            neis_url = f"https://open.neis.go.kr/hub/schoolInfo?Type=json&SCHUL_NM={name.strip()}"
            neis_res = requests.get(neis_url, timeout=5).json()
            if "schoolInfo" in neis_res:
                for row in neis_res["schoolInfo"][1]["row"]:
                    neis_map[row["SCHUL_NM"]] = {
                        "officeCode": row["ATPT_OFCDC_SC_CODE"],
                        "schoolCode": row["SD_SCHUL_CODE"]
                    }
        except Exception:
            pass

        result_list = []
        for s in comcigan_list:
            matched_neis = {}
            for neis_name, neis_data in neis_map.items():
                if s["name"] in neis_name or neis_name in s["name"]:
                    matched_neis = neis_data
                    break
            
            result_list.append({
                "name": s["name"],
                "region": s["region"],
                "comciganCode": s["comciganCode"],
                "officeCode": matched_neis.get("officeCode", ""),
                "schoolCode": matched_neis.get("schoolCode", "")
            })

        return {"list": result_list}
    except Exception as e:
        return {"error": str(e), "list": []}

@app.get("/api/timetable")
def get_timetable(
    schoolName: str = Query(""),
    comciganCode: str = Query(""),
    grade: int = Query(...),
    classNum: int = Query(...)
):
    target = schoolName.strip() if schoolName.strip() else comciganCode.strip()
    if not target:
        return {"error": "학교 정보가 없습니다.", "data": []}

    try:
        tt = TimeTable(target, week_num=0)
        class_schedule = tt.timetable[grade][classNum]

        week_data = []
        # 요일 매핑 (1=월요일 ~ 5=금요일)
        for day in range(1, 6):
            day_list = []
            try:
                day_periods = class_schedule[day] # List[TimeTableData]
                for item in day_periods:
                    sub_text = item.subject.strip() if getattr(item, 'subject', None) else "수업 없음"
                    teacher_text = item.teacher.strip() if getattr(item, 'teacher', None) else ""
                    is_changed = getattr(item, 'replaced', False)
                    period_num = getattr(item, 'period', 0)

                    day_list.append({
                        "period": period_num,
                        "subject": sub_text,
                        "teacher": teacher_text,
                        "changed": is_changed
                    })
            except (KeyError, IndexError):
                pass
                
            week_data.append(day_list)

        return {"source": "live", "data": week_data}
    except Exception as e:
        return {"error": str(e), "data": []}

@app.get("/api/meal")
def get_meal(
    officeCode: str = Query(""),
    schoolCode: str = Query(""),
    schoolName: str = Query(""),
    ymd: str = Query("")
):
    if not ymd:
        return {"data": {"dishes": [], "calorie": ""}}

    # 교육청/학교 코드가 비어있다면 학교명으로 나이스 API 직접 재검색
    if (not officeCode or not schoolCode) and schoolName:
        try:
            s_url = f"https://open.neis.go.kr/hub/schoolInfo?Type=json&SCHUL_NM={schoolName.strip()}"
            s_res = requests.get(s_url, timeout=5).json()
            if "schoolInfo" in s_res:
                row = s_res["schoolInfo"][1]["row"][0]
                officeCode = row["ATPT_OFCDC_SC_CODE"]
                schoolCode = row["SD_SCHUL_CODE"]
        except Exception:
            pass

    if not officeCode or not schoolCode:
        return {"data": {"dishes": [], "calorie": ""}}

    # 나이스 공식 급식 정보 API 호출
    try:
        url = f"https://open.neis.go.kr/hub/mealServiceDietInfo?Type=json&ATPT_OFCDC_SC_CODE={officeCode}&SD_SCHUL_CODE={schoolCode}&MLSV_YMD={ymd}"
        res = requests.get(url, timeout=5).json()

        if "mealServiceDietInfo" in res:
            row = res["mealServiceDietInfo"][1]["row"][0]
            raw_dish = row.get("DDISH_NM", "")
            # 알레르기 번호 및 태그 제거
            cleaned_dishes = [d.strip() for d in re.sub(r"[0-9*.<br/>\(\)]", "", raw_dish).split() if d.strip()]
            return {
                "source": "live",
                "data": {
                    "dishes": cleaned_dishes,
                    "calorie": row.get("CAL_INFO", "")
                }
            }
        return {"data": {"dishes": [], "calorie": ""}}
    except Exception:
        return {"error": "급식 불러오기 실패", "data": {"dishes": [], "calorie": ""}}
