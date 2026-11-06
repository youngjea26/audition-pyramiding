"""실시간 엔진: 시세(Tick) → 상태 머신 → Live Score → 이벤트 저장. 시세 공급자와 무관하다(Provider Adapter).

흐름
  1) 배치가 만든 기준(baselines)으로 게이트를 통과한 종목만 추적한다.
  2) 모든 추적 종목을 매 틱마다 상태 머신에 넣는다(싸다).
  3) 신고가 -5% 이내이거나 돌파 상태인 종목에만 정밀분석(상대 거래량·캔들·업종 동반)을 한다.
  4) 상태가 바뀔 때만 이벤트를 DB(state_events)에 남기고, 현재 상태는 state_current 에 보존한다.
주문 기능은 없다.
"""
import json

from . import live, states as S
from .config import PARAMS as P

BREAK_STATES = ("INTRADAY_BREAKOUT", "CONFIRMED_BREAKOUT", "REBREAKOUT")


class Engine:
    def __init__(self, baselines, conn=None, curve=None):
        """baselines: {종목코드: 기준 dict(high_52w_prev, avg_vol20, sector, score_total, gate_pass, bbw, atr_pct, ...)}"""
        self.base = {s: b for s, b in baselines.items() if b.get("gate_pass")}
        self.states = {s: S.StockState(s) for s in self.base}
        self.conn = conn
        self.curve = curve or live.DEFAULT_CURVE
        self.day = ""
        self.last = {}
        self.live = {}                      # 종목 → 최신 정밀분석 결과(UI 표시용)
        if conn is not None:
            self._restore()

    # ───────── 저장·복원
    def _restore(self):
        for r in self.conn.execute("SELECT * FROM state_current"):
            st = self.states.get(r["symbol"])
            if st:
                st.state, st.since = r["state"], r["since"] or ""
                st.breakout_level, st.breakout_date = r["breakout_level"] or 0.0, r["breakout_date"] or ""
                st.ext_peak, st.bbw_at_ext = r["ext_peak"] or 0.0, r["bbw_at_ext"] or 0.0
                st.atr_pct_at_ext, st.consol_high = r["atr_pct_at_ext"] or 0.0, r["consol_high"] or 0.0

    def _save_state(self, st, ts):
        if self.conn is None:
            return
        self.conn.execute(
            "INSERT INTO state_current (symbol,state,since,breakout_level,breakout_date,ext_peak,bbw_at_ext,"
            "atr_pct_at_ext,consol_high,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "state=excluded.state,since=excluded.since,breakout_level=excluded.breakout_level,"
            "breakout_date=excluded.breakout_date,ext_peak=excluded.ext_peak,bbw_at_ext=excluded.bbw_at_ext,"
            "atr_pct_at_ext=excluded.atr_pct_at_ext,consol_high=excluded.consol_high,updated_at=excluded.updated_at",
            (st.symbol, st.state, st.since, st.breakout_level, st.breakout_date, st.ext_peak, st.bbw_at_ext,
             st.atr_pct_at_ext, st.consol_high, ts))

    def _log(self, ev, ts, volume, live_score, payload):
        if self.conn is not None:
            self.conn.execute("INSERT INTO state_events (symbol,ts,kind,price,volume,live_score,payload) VALUES (?,?,?,?,?,?,?)",
                              (ev["symbol"], ts, ev["kind"], ev["price"], volume, live_score,
                               json.dumps(payload, ensure_ascii=False)))

    # ───────── 거래일 흐름
    def begin_session(self, day):
        self.day, self.last, self.live = day, {}, {}
        for s, st in self.states.items():
            S.start_session(st, self.base[s], day)
            for ev in S.drain(st):
                self._log(ev, day + " 08:59:00", None, None, {"phase": "session_start"})
            self._save_state(st, day)
        if self.conn is not None:
            self.conn.commit()

    def _level(self, st, base):
        return st.breakout_level if st.state in BREAK_STATES + ("EXTENDED", "REBREAKOUT_WAIT") and st.breakout_level \
            else base["high_52w_prev"]

    def _n_other_breaking(self, symbol, sector):
        if not sector:
            return 0
        return sum(1 for s, st in self.states.items()
                   if s != symbol and self.base[s].get("sector") == sector and st.broke_today and st.state in BREAK_STATES)

    def on_tick(self, tick):
        """시세 한 건을 처리하고, 이번에 생긴 이벤트 목록을 돌려준다."""
        st = self.states.get(tick.symbol)
        if st is None:
            return []
        base = self.base[tick.symbol]
        self.last[tick.symbol] = tick
        S.on_tick(st, base, tick.price, tick.high)
        gap = (tick.price / base["high_52w_prev"] - 1) * 100
        info = None
        if gap >= P.near_pct or st.state in BREAK_STATES:               # 정밀분석 대상: 신고가 -5% 이내 또는 돌파 상태
            parts = live.live_components(tick, base, self._level(st, base),
                                         self._n_other_breaking(tick.symbol, base.get("sector")), self.curve)
            info = {"gap_pct": round(gap, 2), "live_score": round(base.get("score_total", 0) + parts["live_pts"], 2), **parts}
        self.live[tick.symbol] = info
        events = S.drain(st)
        for ev in events:
            ev["live_score"] = info["live_score"] if info else None
            ev["ts"] = tick.ts
            self._log(ev, tick.ts, tick.cum_vol, ev["live_score"], info or {})
            self._save_state(st, tick.ts)
        if events and self.conn is not None:
            self.conn.commit()
        return events

    def end_session(self):
        """종가 확정. 마지막으로 받은 시세를 종가로 보고 종가 확정 이벤트(CONFIRMED / FAILED ...)를 만든다."""
        out = []
        for s, t in self.last.items():
            st = self.states[s]
            S.on_close(st, self.base[s], t.price, t.high)
            for ev in S.drain(st):
                ev["ts"] = t.ts[:8] + " 15:30:00"
                ev["live_score"] = (self.live.get(s) or {}).get("live_score")
                self._log(ev, ev["ts"], t.cum_vol, ev["live_score"], {"phase": "close"})
                out.append(ev)
            self._save_state(st, t.ts)
        if self.conn is not None:
            self.conn.commit()
        return out

    # ───────── 화면용
    def watch_symbols(self, limit):
        """실시간(WebSocket)으로 지켜볼 종목: 돌파 상태 먼저, 그다음 신고가에 가까운 순서. limit 개까지."""
        rank = []
        for s, st in self.states.items():
            t = self.last.get(s)
            price = t.price if t else self.base[s].get("close", 0)
            gap = price / self.base[s]["high_52w_prev"] - 1
            if st.state in BREAK_STATES or gap >= P.near_pct / 100:
                rank.append((0 if st.state in BREAK_STATES else 1, -gap, s))
        return [s for _, _, s in sorted(rank)[:limit]]

    def rows(self):
        out = []
        for s, st in self.states.items():
            b, t = self.base[s], self.last.get(s)
            price = t.price if t else b.get("close")
            out.append({"symbol": s, "name": b.get("name"), "sector": b.get("sector"), "state": st.state,
                        "price": price, "high_52w_prev": b["high_52w_prev"],
                        "gap_pct": round((price / b["high_52w_prev"] - 1) * 100, 2) if price else None,
                        "static_score": b.get("score_total"), "live": self.live.get(s),
                        "rs1m": b.get("rs1m"), "rs3m": b.get("rs3m"), "fund_status": b.get("fund_status"),
                        "ma5w": b.get("ma5w"), "avg_val20": b.get("avg_val20"), "caution": b.get("caution"),
                        "since": st.since, "breakout_level": st.breakout_level or None, "broke_today": bool(st.broke_today)})
        return out
