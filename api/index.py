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
    if not name:
        return ""
    name = name.strip()
    if len(name) == 2 and not name.endswith("*"):
        return name + "*"
    return name

@app.get("/api/search-school")
def search_school(name: str = Query(..., min_length=2)):
    try:
        search_kw = name.strip()
        schools = get_school_code(search_kw)
        
        # 💡 [보강] "부산신정고"처럼 지역명을 붙여 검색한 경우 지역명 분리 후 재시도
        if not schools:
            regions = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
            clean_name = search_kw
            for r in regions:
                if clean_name.startswith(r) and len(clean_name) > len(r) + 1:
                    clean_name = clean_name[len(r):].strip()
                    break
            if clean_name != search_kw:
                schools = get_school_code(clean_name)
                search_kw = clean_name

        comcigan_list = []
        for s in schools:
            comcigan_list.append({
                "localCode": str(s[0]),    # 💡 지역 코드 (동명 학교 구분용)
                "region": str(s[1]),       # 지역명
                "name": str(s[2]),         # 학교명
                "comciganCode": str(s[3])  # 학교 코드
            })

        # 나이스(NEIS) 학교 검색
        neis_list = []
        try:
            neis_url = f"https://open.neis.go.kr/hub/schoolInfo?Type=json&SCHUL_NM={search_kw}"
            neis_res = requests.get(neis_url, timeout=5).json()
            if "schoolInfo" in neis_res:
                for row in neis_res["schoolInfo"][1]["row"]:
                    neis_list.append({
                        "name": row.get("SCHUL_NM", ""),
                        "officeName": row.get("ATPT_OFCDC_SC_NM", ""),
                        "location": row.get("LCTN_SC_NM", ""),
                        "officeCode": row.get("ATPT_OFCDC_SC_CODE", ""),
                        "schoolCode": row.get("SD_SCHUL_CODE", "")
                    })
        except Exception:
            pass

        # 💡 [핵심] 동명 학교(신정고 등)인 경우 '지역'까지 비교하여 올바른 교육청/학교 코드 매칭
        result_list = []
        for s in comcigan_list:
            matched_neis = {}
            for n in neis_list:
                name_match = (s["name"] in n["name"] or n["name"] in s["name"])
                region_match = (s["region"] in n["location"] or s["region"] in n["officeName"])
                if name_match and region_match:
                    matched_neis = n
                    break
            
            # 지역 대조 실패 시 이름만으로 폴백
            if not matched_neis:
                for n in neis_list:
                    if s["name"] in n["name"] or n["name"] in s["name"]:
                        matched_neis = n
                        break
            
            result_list.append({
                "localCode": s["localCode"],
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
    localCode: str = Query(""),
    grade: int = Query(...),
    classNum: int = Query(...)
):
    target = schoolName.strip()
    if not target:
        return {"error": "학교 정보가 없습니다.", "data": []}

    sc_code = int(comciganCode) if comciganCode and comciganCode.isdigit() else 0
    loc_code = int(localCode) if localCode and localCode.isdigit() else 0

    try:
        # 💡 [핵심] 동명 학교 충돌(RuntimeError) 방지를 위해 local_code와 school_code를 명시적으로 전달!
        tt = TimeTable(school_name=target, local_code=loc_code, school_code=sc_code, week_num=0)
    except Exception:
        try:
            # 예외 발생 시 학교명만으로 재시도
            tt = TimeTable(school_name=target, week_num=0)
        except Exception as e:
            return {"error": str(e), "data": []}

    try:
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