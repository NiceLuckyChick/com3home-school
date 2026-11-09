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
        
        # 💡 [핵심 수정] 실제 pycomcigan 1.4.3 응답 순서에 맞게 정확히 매핑!
        # 응답 구조: [지역코드(0), 지역명(1), 학교명(2), 학교코드(3)]
        for s in schools:
            comcigan_list.append({
                "region": str(s[1]),      # 지역명 (예: 경기)
                "name": str(s[2]),        # 학교명 (예: XX고등학교)
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

        # 💡 [급식 오류 수정] 컴시간 학교명과 나이스 학교명이 미세하게 달라도 매칭되게 처리
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
        for day_periods in class_schedule:
            day_list = []
            for p_idx, subject in enumerate(day_periods):
                sub_text = subject.strip() if subject else "수업 없음"
                day_list.append({
                    "period": p_idx + 1,
                    "subject": sub_text,
                    "teacher": "",
                    "changed": False
                })
            week_data.append(day_list)

        return {"source": "live", "data": week_data}
    except Exception as e:
        return {"error": str(e), "data": []}

@app.get("/api/meal")
def get_meal(officeCode: str = Query(""), schoolCode: str = Query(""), ymd: str = Query("")):
    if not officeCode or not schoolCode or not ymd:
        return {"data": {"dishes": [], "calorie": ""}}
    try:
        url = f"https://open.neis.go.kr/hub/mealServiceDietInfo?Type=json&ATPT_OFCDC_SC_CODE={officeCode}&SD_SCHUL_CODE={schoolCode}&MLSV_YMD={ymd}"
        res = requests.get(url, timeout=5).json()

        if "mealServiceDietInfo" in res:
            row = res["mealServiceDietInfo"][1]["row"][0]
            raw_dish = row.get("DDISH_NM", "")
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
