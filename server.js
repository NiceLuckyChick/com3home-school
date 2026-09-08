import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);

// 💡 [핵심] Render 서버에서도 라이브러리 버그가 자동으로 고쳐지도록 런타임 패치!
try {
  const constants = require('comcigan.ts/dist/constants.js');
  if (constants && constants.RegExes) {
    constants.RegExes.TeacherCode = /(?<=자료\.자료)\d+(?=\[th\])/;
  }
} catch (e) {
  console.log('패치 알림:', e.message);
}

import ComciganModule from 'comcigan.ts';
const Comcigan = typeof ComciganModule === 'function' 
  ? ComciganModule 
  : (ComciganModule.default || ComciganModule);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const comcigan = new Comcigan();

// 캐시 (시간표 1시간, 급식 12시간)
const cache = { timetable: {}, meal: {} };
const TIMETABLE_CACHE_TIME = 60 * 60 * 1000;
const MEAL_CACHE_TIME = 12 * 60 * 60 * 1000;

// 1. [학교 검색 API]
app.get('/api/search-school', async (req, res) => {
  try {
    const { name } = req.query;
    if (!name || name.trim().length < 2) {
      return res.status(400).json({ error: '학교 이름을 2자 이상 입력해주세요.' });
    }

    const keyword = name.trim();

    // 컴시간 학교 검색
    let comciganSchools = [];
    try {
      const result = await comcigan.searchSchools(keyword);
      comciganSchools = result.map(s => ({
        comciganCode: s.code,
        name: s.name,
        region: s.region?.name || ''
      }));
    } catch (e) {
      console.log('컴시간 검색 실패:', e.message);
    }

    // 나이스 학교 정보 검색 (급식용)
    let neisMap = {};
    try {
      const neisRes = await fetch(`https://open.neis.go.kr/hub/schoolInfo?Type=json&SCHUL_NM=${encodeURIComponent(keyword)}`);
      const neisJson = await neisRes.json();
      if (neisJson.schoolInfo) {
        neisJson.schoolInfo[1].row.forEach(row => {
          neisMap[row.SCHUL_NM] = {
            officeCode: row.ATPT_OFCDC_SC_CODE,
            schoolCode: row.SD_SCHUL_CODE
          };
        });
      }
    } catch (e) {}

    const list = comciganSchools.map(s => {
      const neis = neisMap[s.name] || {};
      return {
        name: s.name,
        region: s.region,
        comciganCode: s.comciganCode,
        officeCode: neis.officeCode || '',
        schoolCode: neis.schoolCode || ''
      };
    });

    res.json({ list });
  } catch (err) {
    console.error('검색 에러:', err);
    res.status(500).json({ error: '검색 중 오류가 발생했습니다.' });
  }
});

// 2. [주간 시간표 API]
app.get('/api/timetable', async (req, res) => {
  try {
    const { comciganCode, grade, classNum } = req.query;
    if (!comciganCode || !grade || !classNum) {
      return res.status(400).json({ error: '필수 정보가 누락되었습니다.' });
    }

    const cacheKey = `${comciganCode}-${grade}-${classNum}`;

    if (cache.timetable[cacheKey] && Date.now() - cache.timetable[cacheKey].time < TIMETABLE_CACHE_TIME) {
      return res.json({ source: 'cache', data: cache.timetable[cacheKey].data });
    }

    const rawWeek = await comcigan.getTimetable(Number(comciganCode), Number(grade), Number(classNum));

    const weekData = (rawWeek || []).slice(0, 5).map((dayPeriods) => {
      return (dayPeriods || []).map((p, pIdx) => ({
        period: pIdx + 1,
        subject: p.subject || '수업 없음',
        teacher: p.teacher || '',
        changed: p.changed || false,
        originalSubject: p.originalSubject || '',
        originalTeacher: p.originalTeacher || ''
      }));
    });

    cache.timetable[cacheKey] = { time: Date.now(), data: weekData };
    res.json({ source: 'live', data: weekData });
  } catch (error) {
    console.error('시간표 에러:', error);
    res.status(500).json({ error: '시간표를 불러오는 중 오류가 발생했습니다.' });
  }
});

// 3. [급식표 API]
app.get('/api/meal', async (req, res) => {
  try {
    const { officeCode, schoolCode, ymd } = req.query;
    if (!officeCode || !schoolCode || !ymd) {
      return res.json({ data: { dishes: [], calorie: '' } });
    }

    const cacheKey = `${schoolCode}-${ymd}`;
    if (cache.meal[cacheKey] && Date.now() - cache.meal[cacheKey].time < MEAL_CACHE_TIME) {
      return res.json({ source: 'cache', data: cache.meal[cacheKey].data });
    }

    const url = `https://open.neis.go.kr/hub/mealServiceDietInfo?Type=json&ATPT_OFCDC_SC_CODE=${officeCode}&SD_SCHUL_CODE=${schoolCode}&MLSV_YMD=${ymd}`;
    const response = await fetch(url);
    const json = await response.json();

    if (json.mealServiceDietInfo) {
      const row = json.mealServiceDietInfo[1].row[0];
      const cleanedDishes = row.DDISH_NM
        .replace(/[0-9*.<br/>\(\)]/g, '')
        .split(' ')
        .filter((d) => d.trim() !== '');

      const result = { dishes: cleanedDishes, calorie: row.CAL_INFO };
      cache.meal[cacheKey] = { time: Date.now(), data: result };
      return res.json({ source: 'live', data: result });
    }

    res.json({ source: 'live', data: { dishes: [], calorie: '' } });
  } catch (error) {
    res.status(500).json({ error: '급식 불러오기 실패' });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🚀 Com3home 서비스 시작됨: http://localhost:${PORT}`);
});