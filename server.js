import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import { execFile } from 'child_process';
import util from 'util';

const execFilePromise = util.promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// 캐시 (시간표 1시간, 급식 12시간)
const cache = { timetable: {}, meal: {} };
const TIMETABLE_CACHE_TIME = 60 * 60 * 1000;
const MEAL_CACHE_TIME = 12 * 60 * 60 * 1000;

// 1. [학교 검색 API] - pycomcigan 1.4.3 연동
app.get('/api/search-school', async (req, res) => {
  try {
    const { name } = req.query;
    if (!name || name.trim().length < 2) {
      return res.status(400).json({ error: '학교 이름을 2자 이상 입력해주세요.' });
    }

    const keyword = name.trim();

    // Python 브릿지 실행 (검색)
    const { stdout } = await execFilePromise('python', ['bridge.py', 'search', keyword]);
    const parsed = JSON.parse(stdout);
    const comciganSchools = parsed.list || [];

    // 나이스 학교 정보 검색 (급식용 코드)
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

// 2. [주간 시간표 API] - pycomcigan 1.4.3 암호화 해제된 데이터 가져오기
app.get('/api/timetable', async (req, res) => {
  try {
    const { schoolName, grade, classNum } = req.query;
    if (!schoolName || !grade || !classNum) {
      return res.status(400).json({ error: '필수 정보가 누락되었습니다.' });
    }

    const cacheKey = `${schoolName}-${grade}-${classNum}`;
    if (cache.timetable[cacheKey] && Date.now() - cache.timetable[cacheKey].time < TIMETABLE_CACHE_TIME) {
      return res.json({ source: 'cache', data: cache.timetable[cacheKey].data });
    }

    // Python 브릿지 실행 (시간표 조회)
    const { stdout } = await execFilePromise('python', ['bridge.py', 'timetable', schoolName, String(grade), String(classNum)]);
    const parsed = JSON.parse(stdout);

    if (parsed.error) {
      return res.status(500).json({ error: parsed.error });
    }

    const weekData = parsed.data || [];
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