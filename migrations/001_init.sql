-- 52주 신고가 매매 — 초기 스키마 (SQLite)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 배치(저녁)가 종목마다 하루 한 줄씩 저장하는 기준 지표. asof 는 마지막 자료일(D). D+1 장의 기준이 된다.
CREATE TABLE IF NOT EXISTS daily_metrics (
    symbol            TEXT NOT NULL,
    asof              TEXT NOT NULL,
    name              TEXT,
    market            TEXT,
    sector            TEXT,
    mcap              INTEGER,
    close             REAL,
    high_52w_prev     REAL,      -- 최근 250거래일 일봉 고가 최댓값(D 포함, 분할 보정)
    high_52w_date     TEXT,
    gap_to_high       REAL,      -- close / high_52w_prev - 1
    rs1m              REAL,
    rs3m              REAL,
    fund_status       TEXT,      -- PASS / TURNAROUND / FAIL / UNKNOWN
    fund_grade        TEXT,
    ma5w              REAL,
    ma5w_up           INTEGER,
    ma20w             REAL,
    above_ma20w       INTEGER,
    ma240d            REAL,
    above_ma240d      INTEGER,
    bbw               REAL,
    bbw_pctile        REAL,
    atr14             REAL,
    atr_pct           REAL,
    adx14             REAL,
    sector_rs         REAL,
    sector_near_ratio REAL,
    avg_vol20         REAL,
    vol5_ratio        REAL,      -- 5일 평균 거래량 / 20일 평균 거래량(수렴 판정)
    high_10d          REAL,      -- 최근 10거래일 고가(수렴 구간 고점의 출발점)
    avg_val20         REAL,
    risk_excluded     INTEGER NOT NULL DEFAULT 0,
    risk_reason       TEXT,
    caution           INTEGER NOT NULL DEFAULT 0,   -- 투자주의(표시만)
    gate_pass         INTEGER NOT NULL DEFAULT 0,
    gate_fail         TEXT,
    PRIMARY KEY (symbol, asof)
);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_asof ON daily_metrics (asof, gate_pass);

CREATE TABLE IF NOT EXISTS scores (
    symbol      TEXT NOT NULL,
    asof        TEXT NOT NULL,
    rs          REAL,
    fundamental REAL,
    industry    REAL,
    quality     REAL,
    trend       REAL,
    total       REAL,          -- 정적 점수(최대 84). 장중 가변 항목(최대 16)은 실시간 엔진이 더한다
    PRIMARY KEY (symbol, asof)
);

-- 종목별 현재 상태. 날짜를 넘어 이어져야 하는 값(돌파 기준가, 수렴 구간 고점 등)을 함께 보존한다.
CREATE TABLE IF NOT EXISTS state_current (
    symbol         TEXT PRIMARY KEY,
    state          TEXT NOT NULL,
    since          TEXT,
    breakout_level REAL,       -- 돌파 당시의 52주 최고가
    breakout_date  TEXT,
    ext_peak       REAL,       -- EXTENDED 구간 최고가
    bbw_at_ext     REAL,
    atr_pct_at_ext REAL,
    consol_high    REAL,       -- REBREAKOUT_WAIT 시작 이후 고점
    updated_at     TEXT
);

-- 상태 전이 이력. 장중 돌파와 종가 확정은 서로 다른 kind 로 남긴다.
CREATE TABLE IF NOT EXISTS state_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT NOT NULL,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,   -- 상태 이름 또는 INTRADAY_BREAKOUT / CONFIRMED_BREAKOUT / FAILED_BREAKOUT ...
    price      REAL,
    volume     REAL,
    live_score REAL,
    payload    TEXT
);
CREATE INDEX IF NOT EXISTS idx_state_events_ts ON state_events (ts);
CREATE INDEX IF NOT EXISTS idx_state_events_symbol ON state_events (symbol, ts);

-- 장중 스냅샷(상대 거래량 기준선 구축용). 오래된 것은 주기적으로 지운다.
CREATE TABLE IF NOT EXISTS intraday_snapshots (
    symbol  TEXT NOT NULL,
    ts      TEXT NOT NULL,
    price   REAL,
    high    REAL,
    cum_vol REAL,
    cum_val REAL,
    PRIMARY KEY (symbol, ts)
);

-- 시각(분)별 «하루 거래량 대비 누적 거래량 비율». 스냅샷이 쌓이면 일반 곡선을 이것으로 대체한다.
CREATE TABLE IF NOT EXISTS volume_profile (
    symbol  TEXT NOT NULL,
    minute  INTEGER NOT NULL,   -- 09:00 = 0
    ratio   REAL NOT NULL,
    samples INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, minute)
);
