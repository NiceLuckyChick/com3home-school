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

def format_teacher_name(name: str) -> str:
    """선생님 이름이 2글자이면 끝에 *를 붙여 3글자 형태로 보정"""
    if not name:
        return ""
    name = name.strip()
    if len(name) == 2 and not name.endswith("*"):
        return name + "*"
    return name

@app.get("/api/search-school")
def search_school(name: str = Query(..., min_length=2)):
    try:
        schools = get_school_code(name.strip())
        comcigan_list = []
        
        for s in schools:
            comcigan_list.append({
                "region": str(s[1]),      
                "name": str(s[2]),        
                "comciganCode": str(s[3]) 
            })

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
        for day in range(1, 6):
            day_list = []
            try:
                day_periods = class_schedule[day]
                for item in day_periods:
                    sub_text = item.subject.strip() if getattr(item, 'subject', None) else "수업 없음"
                    teacher_text = format_teacher_name(getattr(item, 'teacher', ''))
                    is_changed = getattr(item, 'replaced', False)
                    period_num = getattr(item, 'period', 0)

                    # 💡 [변경 전 수업 정보 추출]
                    original_info = None
                    if is_changed and hasattr(item, 'original') and item.original:
                        orig = item.original
                        orig_sub = getattr(orig, 'subject', '').strip() if getattr(orig, 'subject', None) else ""
                        orig_teacher = format_teacher_name(getattr(orig, 'teacher', ''))
                        original_info = {
                            "period": getattr(orig, 'period', 0),
                            "subject": orig_sub,
                            "teacher": orig_teacher
                        }

                    day_list.append({
                        "period": period_num,
                        "subject": sub_text,
                        "teacher": teacher_text,
                        "changed": is_changed,
                        "original": original_info
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
