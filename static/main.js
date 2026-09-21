(function () {
  "use strict";

  const socket = io();

  const S = {
    mySid: null, oppSid: null, matchId: null,
    myName: "You", oppName: "Opponent",
    round: 1, myScore: 0, oppScore: 0,
    phase: "idle", signalTime: 0, hasTapped: false,
  };

  const $ = (id) => document.getElementById(id);
  const screens = { start: $("screen-start"), queue: $("screen-queue"), game: $("screen-game") };
  const arena = $("arena"), bigText = $("big-text"), subText = $("sub-text");
  const statusText = $("status-text");
  const youNameEl = $("you-name"), oppNameEl = $("opp-name");
  const youScoreEl = $("you-score"), oppScoreEl = $("opp-score");
  const roundNumEl = $("round-num");
  const overlay = $("result-overlay"), resultIcon = $("result-icon");
  const resultTitle = $("result-title"), resultSub = $("result-sub");
  const resultYou = $("result-you"), resultOpp = $("result-opp");
  const nameInput = $("name-input");

  function showScreen(name) {
    Object.keys(screens).forEach(k =>
      screens[k].classList.toggle("active", k === name));
  }
  function setArena(state) {
    arena.className = "arena" + (state ? " state-" + state : "");
  }
  function updateScores() {
    youScoreEl.textContent = S.myScore;
    oppScoreEl.textContent = S.oppScore;
  }
  function pulseBig() {
    bigText.classList.remove("pulse");
    void bigText.offsetWidth;
    bigText.classList.add("pulse");
  }

  // ---------- Socket ----------
  socket.on("connect", () => { S.mySid = socket.id; });

  socket.on("queue_joined", () => {
    S.phase = "queue"; showScreen("queue");
  });
  socket.on("queue_left", () => {
    S.phase = "idle"; showScreen("start");
  });
  socket.on("queue_error", (d) => {
    statusText.textContent = (d && d.message) || "Error";
  });

  socket.on("match_found", (d) => {
    S.matchId = d.match_id; S.mySid = d.you;
    S.oppSid = d.opponent.sid; S.oppName = d.opponent.name || "Opponent";
    S.myScore = 0; S.oppScore = 0; S.round = 1; S.hasTapped = false;
    youNameEl.textContent = S.myName;
    oppNameEl.textContent = S.oppName;
    roundNumEl.textContent = "1";
    updateScores();
    showScreen("game");
    setArena("countdown");
    bigText.textContent = "Get Ready…";
    subText.textContent = "";
    statusText.textContent = "Match starting…";
  });

  socket.on("round_start", (d) => {
    S.round = d.round;
    S.myScore = d.scores[S.mySid] || 0;
    S.oppScore = d.scores[S.oppSid] || 0;
    S.hasTapped = false; S.phase = "countdown";
    roundNumEl.textContent = d.round;
    updateScores();
    setArena("countdown");
    bigText.textContent = "Get Ready…";
    subText.textContent = "Round " + d.round;
    statusText.textContent = "Get ready…";
  });

  socket.on("countdown", (d) => {
    const c = d.count;
    if (c >= 1) {
      S.phase = "countdown"; setArena("countdown");
      bigText.textContent = String(c);
      subText.textContent = "";
      pulseBig();
      statusText.textContent = "Wait for the signal…";
    } else {
      S.phase = "hold"; setArena("hold");
      bigText.textContent = "Wait…";
      bigText.classList.remove("pulse");
      subText.textContent = "Tap only on GREEN";
      statusText.textContent = "Ready…";
    }
  });

  socket.on("signal", () => {
    S.phase = "active"; S.hasTapped = false;
    S.signalTime = performance.now();
    setArena("active");
    statusText.textContent = "GO!";
  });

  socket.on("opponent_tapped", () => {
    if (S.phase === "active" && !S.hasTapped) {
      subText.textContent = "Opponent tapped!";
    }
  });

  socket.on("round_result", (d) => {
    S.phase = "resolved";
    S.myScore = d.scores[S.mySid] || 0;
    S.oppScore = d.scores[S.oppSid] || 0;
    updateScores();

    if (d.reason === "false_start") {
      if (d.false_start === S.mySid) {
        setArena("falsestart");
        bigText.textContent = "FALSE START";
        subText.textContent = "You tapped too early";
        statusText.textContent = "Round lost";
      } else {
        setArena("win");
        bigText.textContent = "ROUND WON";
        subText.textContent = "Opponent false-started";
        statusText.textContent = "Round won!";
      }
      return;
    }
    if (d.replay) {
      setArena("hold");
      bigText.textContent = "NO TAPS";
      subText.textContent = "Replaying round…";
      return;
    }
    if (d.winner === S.mySid) {
      setArena("win");
      bigText.textContent = "ROUND WON";
      const myTap = d.taps[S.mySid];
      subText.textContent = myTap ? "You: " + Math.round(myTap) + " ms" : "";
      statusText.textContent = "Round won!";
    } else {
      setArena("lose");
      bigText.textContent = "ROUND LOST";
      const mt = d.taps[S.mySid], ot = d.taps[S.oppSid];
      if (mt && ot) subText.textContent = "You: " + Math.round(mt) + " · Opp: " + Math.round(ot) + " ms";
      else if (mt) subText.textContent = "You: " + Math.round(mt) + " ms";
      else subText.textContent = "Opponent was faster";
      statusText.textContent = "Round lost";
    }
  });

  socket.on("match_over", (d) => {
    S.phase = "finished";
    const won = d.winner === S.mySid;
    showResult(won, d.scores[S.mySid] || 0, d.scores[S.oppSid] || 0,
      won ? "You won the match!" : "Better luck next time.");
  });

  socket.on("opponent_left", (d) => {
    S.phase = "finished";
    showResult(true, d.scores[S.mySid] || 0, d.scores[S.oppSid] || 0,
      "Opponent disconnected.");
  });

  // ---------- Tap ----------
  function handleTap() {
    if (S.phase === "countdown" || S.phase === "hold") {
      S.phase = "resolved";
      socket.emit("tap", { false_start: true });
      setArena("falsestart");
      bigText.textContent = "FALSE START";
      subText.textContent = "You tapped too early";
      statusText.textContent = "False start!";
      return;
    }
    if (S.phase === "active" && !S.hasTapped) {
      S.hasTapped = true;
      const r = performance.now() - S.signalTime;
      S.phase = "resolved";
      socket.emit("tap", { reaction_ms: r, false_start: false });
      setArena("tapped");
      bigText.textContent = Math.round(r) + " ms";
      subText.textContent = "Waiting for opponent…";
      statusText.textContent = "You tapped in " + Math.round(r) + " ms";
    }
  }

  arena.addEventListener("pointerdown", (e) => { e.preventDefault(); handleTap(); }, { passive: false });
  arena.addEventListener("touchmove", (e) => e.preventDefault(), { passive: false });
  arena.addEventListener("contextmenu", (e) => e.preventDefault());

  // ---------- Result ----------
  function showResult(won, my, opp, reason) {
    resultIcon.textContent = won ? "🏆" : "💀";
    resultTitle.textContent = won ? "VICTORY" : "DEFEAT";
    resultTitle.className = "result-title " + (won ? "win" : "lose");
    resultSub.textContent = reason;
    resultYou.textContent = my;
    resultOpp.textContent = opp;
    overlay.classList.add("show");
  }

  // ---------- Buttons ----------
  $("btn-find").addEventListener("click", () => {
    const raw = (nameInput.value || "").trim();
    S.myName = (raw || "Player").slice(0, 14);
    youNameEl.textContent = S.myName;
    socket.emit("find_match", { name: S.myName });
  });
  $("btn-cancel").addEventListener("click", () => socket.emit("leave_queue"));
  $("btn-again").addEventListener("click", () => {
    overlay.classList.remove("show");
    S.matchId = null; S.oppSid = null;
    S.phase = "idle"; S.hasTapped = false;
    showScreen("start");
    socket.emit("leave_queue");
  });
  nameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("btn-find").click(); }
  });
})();