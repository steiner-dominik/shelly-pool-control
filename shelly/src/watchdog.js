// pool-watchdog.js — tiny independent liveness guard for pool-control.
//
// The main script emits a "pool_hb" event every tick (in-memory, no flash
// wear). If the heartbeat goes stale for > STALE_S the watchdog restarts the
// main script; after MAX_RESTARTS failed restarts it forces the pump relay
// off and keeps trying. Autostart this script together with pool-control.

var MAIN_NAME = "pool-control";
var STALE_S = 120;
var CHECK_MS = 30000;
var MAX_RESTARTS = 2;
var RELAY_ID = 0;

var lastHb = -1;
var restarts = 0;
var mainId = -1;

function up() {
  return Shelly.getComponentStatus("sys").uptime;
}

Shelly.addEventHandler(function (event) {
  if (event !== undefined && event.info !== undefined
      && event.info.event === "pool_hb") {
    lastHb = up();
    restarts = 0;
  }
});

function findMain(cb) {
  Shelly.call("Script.List", {}, function (res) {
    if (res === null || res === undefined || res.scripts === undefined) return;
    for (var i = 0; i < res.scripts.length; i++) {
      if (res.scripts[i].name === MAIN_NAME) {
        mainId = res.scripts[i].id;
        cb();
        return;
      }
    }
  });
}

function restartMain() {
  if (mainId < 0) {
    findMain(restartMain);
    return;
  }
  print("pool-watchdog: heartbeat stale, restarting " + MAIN_NAME);
  Shelly.call("Script.Stop", { id: mainId }, function () {
    Shelly.call("Script.Start", { id: mainId });
  });
}

Timer.set(CHECK_MS, true, function () {
  var u = up();
  if (lastHb < 0) {
    // no heartbeat seen yet since watchdog start — give the main script one
    // stale window from now before acting
    lastHb = u;
    return;
  }
  if (u - lastHb <= STALE_S) return;
  if (restarts < MAX_RESTARTS) {
    restarts += 1;
    lastHb = u;   // grant a fresh window after the restart attempt
    restartMain();
  } else {
    print("pool-watchdog: main script dead, forcing pump off");
    Shelly.call("Switch.Set", { id: RELAY_ID, on: false });
  }
});
