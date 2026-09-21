import eventlet
eventlet.monkey_patch()

import os, random, time, uuid
from flask import Flask, render_template, request
from flask_socketio import SocketIO

# ---------- কনফিগ ----------
ROUNDS_TO_WIN    = 2
MAX_ROUNDS       = 3
COUNTDOWN_STEP   = 0.85
MIN_DELAY        = 2.0
MAX_DELAY        = 5.0
TAP_WINDOW       = 2.5
ROUND_BREAK      = 2.4

app = Flask(__name__)
app.config["SECRET_KEY"] = "speed-tap-secret"
socketio = SocketIO(app, async_mode='threading')

# ---------- মেমরি ----------
waiting_queue = []
matches       = {}
sid_to_match  = {}
sid_names     = {}

# ---------- হেল্পার ----------
def scores(m):
    return {s: m["scores"][s] for s in m["order"]}

def opponent_of(m, sid):
    a, b = m["order"]
    return b if sid == a else a

def player_list(m):
    return [{"sid": s, "name": sid_names.get(s, "Player")} for s in m["order"]]

def broadcast(ev, data, mid):
    socketio.emit(ev, data, room=mid)

def alive(mid, token=None):
    m = matches.get(mid)
    if not m or m["state"] == "finished":
        return None
    if token is not None and m["token"] != token:
        return None
    return m

# ---------- ম্যাচ তৈরি ----------
def create_match(a, b):
    mid = str(uuid.uuid4())
    matches[mid] = {
        "id": mid, "order": [a, b],
        "scores": {a: 0, b: 0}, "round": 0,
        "state": "idle", "taps": {}, "round_winner": None,
        "token": 0, "winner": None,
    }
    sid_to_match[a] = mid
    sid_to_match[b] = mid
    return matches[mid]

def try_matchmake(sid):
    if sid in sid_to_match or sid in waiting_queue:
        return None
    waiting_queue.append(sid)
    if len(waiting_queue) < 2:
        return None
    a = waiting_queue.pop(0)
    b = waiting_queue.pop(0)
    if a == b or a in sid_to_match or b in sid_to_match:
        return None
    return create_match(a, b)

def begin_match(m):
    mid = m["id"]
    for sid in m["order"]:
        socketio.server.enter_room(sid, mid, namespace="/")
    for sid in m["order"]:
        opp = opponent_of(m, sid)
        socketio.emit("match_found", {
            "match_id": mid, "you": sid,
            "opponent": {"sid": opp, "name": sid_names.get(opp, "Player")},
            "players": player_list(m), "scores": scores(m),
            "rounds_to_win": ROUNDS_TO_WIN, "max_rounds": MAX_ROUNDS,
        }, to=sid)
    socketio.start_background_task(start_round_later, mid, 1.0)

# ---------- রাউন্ড ----------
def start_round_later(mid, d):
    socketio.sleep(d)
    start_round(mid)

def start_round(mid):
    m = alive(mid)
    if not m: return
    m["round"] += 1
    m["state"] = "countdown"
    m["taps"] = {}
    m["round_winner"] = None
    m["token"] += 1
    t = m["token"]
    broadcast("round_start", {
        "round": m["round"], "max_rounds": MAX_ROUNDS,
        "rounds_to_win": ROUNDS_TO_WIN, "scores": scores(m),
    }, mid)
    socketio.start_background_task(countdown_signal, mid, t)

def countdown_signal(mid, t):
    m = alive(mid, t)
    if not m: return
    for n in (3, 2, 1):
        if not alive(mid, t): return
        broadcast("countdown", {"count": n}, mid)
        socketio.sleep(COUNTDOWN_STEP)
    m = alive(mid, t)
    if not m or m["state"] != "countdown": return
    m["state"] = "hold"
    broadcast("countdown", {"count": 0}, mid)
    socketio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    m = alive(mid, t)
    if not m or m["state"] != "hold": return
    m["state"] = "active"
    broadcast("signal", {"round": m["round"]}, mid)
    socketio.sleep(TAP_WINDOW)
    m = alive(mid, t)
    if m and m["state"] == "active":
        resolve_round(mid, "timeout")

def resolve_round(mid, reason="taps"):
    m = alive(mid)
    if not m or m["state"] in ("resolved", "idle"): return
    m["state"] = "resolved"
    m["token"] += 1
    a, b = m["order"]
    taps = m["taps"]
    if len(taps) >= 2:
        w = a if taps[a] <= taps[b] else b
    elif len(taps) == 1:
        w = next(iter(taps))
    else:
        w = None
    if w: m["scores"][w] += 1
    m["round_winner"] = w
    broadcast("round_result", {
        "round": m["round"], "winner": w,
        "taps": {s: taps.get(s) for s in m["order"]},
        "scores": scores(m), "reason": reason,
        "replay": w is None, "false_start": None,
    }, mid)
    if w and m["scores"][w] >= ROUNDS_TO_WIN:
        finish_match(mid, w); return
    if w and m["round"] >= MAX_ROUNDS:
        finish_match(mid, w); return
    socketio.start_background_task(next_round, mid, ROUND_BREAK, w is None)

def false_start(mid, sid):
    m = alive(mid)
    if not m or m["state"] in ("resolved", "idle"): return
    opp = opponent_of(m, sid)
    m["state"] = "resolved"
    m["token"] += 1
    m["taps"] = {}
    m["round_winner"] = opp
    m["scores"][opp] += 1
    broadcast("round_result", {
        "round": m["round"], "winner": opp,
        "taps": {s: None for s in m["order"]},
        "scores": scores(m), "reason": "false_start",
        "replay": False, "false_start": sid,
    }, mid)
    if m["scores"][opp] >= ROUNDS_TO_WIN:
        finish_match(mid, opp)
    else:
        socketio.start_background_task(next_round, mid, ROUND_BREAK, False)

def next_round(mid, d, replay):
    socketio.sleep(d)
    m = alive(mid)
    if not m: return
    if replay: m["round"] = max(0, m["round"] - 1)
    start_round(mid)

def finish_match(mid, w):
    m = alive(mid)
    if not m: return
    m["state"] = "finished"
    m["token"] += 1
    m["winner"] = w
    broadcast("match_over", {
        "match_id": mid, "winner": w,
        "scores": scores(m), "players": player_list(m),
    }, mid)
    socketio.start_background_task(cleanup, mid, 1.5)

def cleanup(mid, d=0.0):
    if d: socketio.sleep(d)
    m = matches.pop(mid, None)
    if not m: return
    for sid in m["order"]:
        if sid_to_match.get(sid) == mid:
            sid_to_match.pop(sid, None)
        try:
            socketio.server.leave_room(sid, mid, namespace="/")
        except: pass

# ---------- HTTP ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/healthz")
def healthz():
    return {"status": "ok", "queued": len(waiting_queue), "matches": len(matches)}

# ---------- Socket ইভেন্ট ----------
@socketio.on("connect")
def on_connect():
    socketio.emit("connected", {"sid": request.sid}, to=request.sid)

@socketio.on("find_match")
def on_find(data):
    sid = request.sid
    data = data or {}
    name = str(data.get("name") or "").strip()
    sid_names[sid] = (name[:14] or "Player")
    m = try_matchmake(sid)
    if m is None:
        if sid in waiting_queue:
            socketio.emit("queue_joined", {"position": len(waiting_queue)}, to=sid)
        else:
            socketio.emit("queue_error", {"message": "Already in a match."}, to=sid)
        return
    begin_match(m)

@socketio.on("leave_queue")
def on_leave():
    sid = request.sid
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    socketio.emit("queue_left", {}, to=sid)

@socketio.on("tap")
def on_tap(data):
    sid = request.sid
    data = data or {}
    mid = sid_to_match.get(sid)
    if not mid: return
    m = matches.get(mid)
    if not m or m["state"] in ("resolved", "finished", "idle"): return
    fs = bool(data.get("false_start"))
    if m["state"] in ("countdown", "hold"):
        fs = True
    if fs:
        false_start(mid, sid); return
    if m["state"] != "active": return
    try:
        r = float(data.get("reaction_ms"))
        if r != r or r < 0: return
    except: return
    if sid in m["taps"]: return
    m["taps"][sid] = min(r, TAP_WINDOW * 1000.0)
    socketio.emit("opponent_tapped", {"sid": sid}, room=mid, skip_sid=sid)
    if len(m["taps"]) >= 2:
        resolve_round(mid, "taps")

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    sid_names.pop(sid, None)
    mid = sid_to_match.get(sid)
    if not mid: return
    m = matches.get(mid)
    if not m:
        sid_to_match.pop(sid, None); return
    if m["state"] != "finished":
        opp = opponent_of(m, sid)
        m["state"] = "finished"
        m["token"] += 1
        m["winner"] = opp
        broadcast("opponent_left", {
            "winner": opp, "scores": scores(m),
            "message": "Your opponent disconnected.",
        }, mid)
    socketio.start_background_task(cleanup, mid, 0.6)

# ---------- রান ----------
if __name__ == "__main__":
    print("=" * 50)
    print("  ⚡ SPEED TAP ARENA ⚡")
    print("  http://localhost:5000")
    print("=" * 50)
    socketio.run(app, host="0.0.0.0", port=5000, use_reloader=False)
