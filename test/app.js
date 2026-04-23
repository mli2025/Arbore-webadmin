(function () {
  const statusEl = document.getElementById('status');
  const logEl = document.getElementById('log');
  const btn = document.getElementById('btn');

  function log(line) {
    logEl.textContent += line + "\n";
  }

  statusEl.textContent = "JS loaded";
  statusEl.className = "ok";

  log("User-Agent: " + navigator.userAgent);
  log("Location: " + location.href);
  log("Time: " + new Date().toISOString());

  btn.addEventListener("click", async () => {
    log("\n--- Button clicked ---");
    try {
      const r = await fetch(location.href, { cache: "no-store" });
      log("fetch(self) status: " + r.status);
    } catch (e) {
      log("fetch(self) error: " + (e && e.message ? e.message : String(e)));
    }
    alert("JS is working.");
  });
})();

