"""실시간 서버 실행.

  python -I tools/w52/run_live.py <my-agent 폴더> [--demo] [--host 127.0.0.1] [--port 8052]

환경변수: PROVIDER(kis|mock), LIVE_AUTH_TOKEN(필수), KIS_APP_KEY, KIS_APP_SECRET, KIS_WS_MAX_SUBS, POLL_INTERVAL_SEC, W52_DB_PATH
--demo: 가짜 시세(DemoProvider)와 가짜 시계로 한 거래일을 빠르게 재생한다. 실제 DB 를 건드리지 않는다(메모리 DB).
기본은 127.0.0.1 에서만 연다. 밖으로 보일 때는 Cloudflare Tunnel 같은 터널 뒤에 둔다. 주문 기능은 없다.
"""
import argparse
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from w52 import store  # noqa: E402
from w52.config import env  # noqa: E402
from w52.engine import Engine  # noqa: E402
from w52.server import App, serve  # noqa: E402
from w52.service import LiveService  # noqa: E402

KST = timezone(timedelta(hours=9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8052)
    a = ap.parse_args()
    root = Path(a.root)
    db = env("W52_DB_PATH", str(root / "cache" / "w52" / "w52.db"))
    real = store.connect(db)
    baselines = store.load_baselines(real)
    if not baselines:
        sys.exit("기준 데이터가 없다 — 먼저 `python -I tools/w52/baseline.py <폴더>` 를 실행하라")
    if a.demo:
        from w52.providers.mock import DemoProvider
        provider, conn, poll = DemoProvider(baselines), store.connect(":memory:"), 2
        step = {"n": 0}

        def clock():                                       # 폴링 한 번에 25분씩 흐르는 가짜 시계(월요일 09:00 시작)
            step["n"] += 1
            return datetime(2026, 11, 9, 9, 0, tzinfo=KST) + timedelta(minutes=25 * (step["n"] - 1))
        now = clock
    else:
        from w52.config import provider_name
        name = provider_name()
        if name == "kis":
            from w52.providers.kis import KisProvider
            provider = KisProvider()
        else:
            sys.exit("PROVIDER=%s 는 아직 지원하지 않는다(kis 또는 --demo)" % name)
        conn, poll, now = real, int(env("POLL_INTERVAL_SEC", "40")), None
    engine = Engine(baselines, conn)
    service = LiveService(engine, provider, poll_interval=poll, now=now)
    threading.Thread(target=service.run_forever, daemon=True).start()
    app = App(service, conn, env("LIVE_AUTH_TOKEN"))
    srv = serve(app, a.host, a.port)
    print("서버 시작 http://%s:%d  (모드: %s, 종목 %d개)" % (a.host, a.port, "demo" if a.demo else provider.name, len(engine.states)), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        service.shutdown()


if __name__ == "__main__":
    main()
