/* Opt-in, synthetic browser checks. All HTTP is intercepted; never contacts the Pi. */
const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "../..");
const output =
  process.env.UI_SCREENSHOTS || path.join(root, ".local/ui-checks");
fs.mkdirSync(output, { recursive: true });
const tracks = [
  "Slow morning",
  "A little closer",
  "Sunday kind of love",
  "The quiet hours",
  "Window seat",
  "Until the evening",
  "Softly, softly",
  "A room of our own",
  "Stay for a while",
  "One more song",
].map((title, i) => ({
  number: i + 1,
  title,
  artist: "The Sunday Quartet",
  seconds: 220 + i * 8,
  sectors: 16500 + i * 600,
  ready: true,
  storage: "ready",
}));
function fixture(source, empty = false, ejected = false) {
  return {
    source,
    disc: {
      present: !empty,
      inserted: !ejected,
      ejected,
      id: "TESTDISC1",
      title: "Sunday sessions",
      artist: "The Sunday Quartet",
      cover: empty ? null : "/static/preview-cover.svg",
      metadata_status: "found",
      tracks: empty ? [] : tracks,
    },
    player: {
      state: empty ? "stop" : "pause",
      track: 3,
      elapsed: 82,
      duration: 236,
    },
    queue: { previous: true, upcoming: [4, 5, 6, 7, 8, 9, 10], shuffle: false },
    archive: { stored: 10, total: 10 },
    output: { speaker_connected: true },
    vinyl: { connected: true, available: true, automatic: true, state: "idle" },
    spotify: {
      logged_in: true,
      connected: true,
      title: "A little closer",
      artist: "The Sunday Quartet",
      album: "Sunday sessions",
      cover: "/static/preview-cover.svg",
      available_actions: { skip_next: true, skip_prev: true },
    },
    plexamp: {
      connected: true,
      has_track: true,
      title: "A little closer",
      artist: "The Sunday Quartet",
      album: "Sunday sessions",
      cover: "/static/preview-cover.svg",
      available_actions: { skip_next: true, skip_prev: true },
    },
    dvd: {
      present: true,
      state: "detected",
      title: "The long weekend",
      seconds: 6650,
      dutch_subtitles: true,
      audio_languages: ["Engels", "Nederlands"],
      width: 720,
      height: 576,
      aspect: "16:9",
      movie: {
        title: "The long weekend",
        year: "1998",
        cast: "Een voorbeeldcast",
        cover: "/static/preview-cover.svg",
      },
    },
  };
}
const cover =
  '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600"><rect width="600" height="600" fill="#a3553c"/><circle cx="300" cy="310" r="190" fill="#ecdab7"/><path d="M60 410h480v140H60z" fill="#a3553c"/><text x="48" y="72" fill="#fff1da" font-family="Georgia" font-size="40">Sunday sessions</text><text x="48" y="555" fill="#fff1da" font-family="Arial" font-size="19" letter-spacing="3">THE SUNDAY QUARTET</text></svg>';
(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE
      ? { executablePath: process.env.BROWSER_EXECUTABLE }
      : {}),
  });
  const failures = [];
  try {
    for (const [name, width, height] of [
      ["desktop", 1440, 1000],
      ["phone", 390, 844],
      ["small-phone", 320, 740],
    ]) {
      const context = await browser.newContext({
        viewport: { width, height },
        reducedMotion: "reduce",
        colorScheme: "light",
      });
      const page = await context.newPage();
      let state = fixture("cd");
      page.on("pageerror", (error) => failures.push(error.message));
      await page.route("**/*", async (route) => {
        const request = route.request(),
          url = new URL(request.url());
        if (url.hostname !== "pi-player.test") return route.abort();
        if (url.pathname === "/api/status")
          return route.fulfill({ json: state });
        if (url.pathname === "/api/action") {
          const payload = request.postDataJSON();
          if (payload.action === "source") state = fixture(payload.source);
          return route.fulfill({ json: { ok: true } });
        }
        if (url.pathname === "/static/preview-cover.svg")
          return route.fulfill({ contentType: "image/svg+xml", body: cover });
        const file =
          url.pathname === "/" ? "static/index.html" : url.pathname.slice(1);
        if (!/^static\/[\w.-]+$/.test(file)) return route.abort();
        const types = {
          ".html": "text/html",
          ".js": "text/javascript",
          ".css": "text/css",
          ".jpg": "image/jpeg",
        };
        return route.fulfill({
          contentType: types[path.extname(file)],
          body: fs.readFileSync(path.join(root, file)),
        });
      });
      await page.goto("http://pi-player.test/");
      await page.locator("#track-list .track-row").first().waitFor();
      assert.equal(await page.locator("#queue-section").count(), 0);
      assert.equal(await page.locator("#track-list .track-row").count(), 10);
      assert(await page.locator("#track-heading").isVisible());
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        name + " overflows",
      );
      const first = page.locator(".track-row").first();
      await first.focus();
      state.disc.tracks = state.disc.tracks.map((t, i) =>
        i === 0 ? { ...t, title: "Updated first track" } : t,
      );
      await page.evaluate(() => readStatus());
      assert.equal(
        await page.evaluate(() => document.activeElement.dataset.trackNumber),
        "1",
      );
      state.disc.tracks = tracks.map((t) => ({ ...t }));
      await page.evaluate(async () => {
        await readStatus();
        document.activeElement.blur();
      });
      await page.screenshot({
        path: path.join(output, name + "-cd.png"),
        fullPage: true,
      });
      if (width <= 760) {
        await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
        const lastTrack = await page.locator(".track-row").last().boundingBox();
        const dock = await page.locator(".player-dock").boundingBox();
        assert(
          lastTrack.y + lastTrack.height < dock.y,
          "Last track is obscured by mobile controls",
        );
        await page.evaluate(() => scrollTo(0, 0));
      }
      if (width > 760) {
        state.disc.tracks = Array.from({ length: 26 }, (_, i) => ({
          ...tracks[i % 10],
          number: i + 1,
        }));
        await page.evaluate(() => readStatus());
        await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
        const play = await page.locator("#play").boundingBox();
        assert(
          play.y >= 0 && play.y + play.height <= height,
          "Desktop transport scrolls out of view",
        );
        await page.screenshot({
          path: path.join(output, name + "-long-album.png"),
          fullPage: true,
        });
        await page.evaluate(() => scrollTo(0, 0));
      }
      state = fixture("cd", false, true);
      await page.evaluate(() => readStatus());
      assert(await page.locator("#eject").isDisabled());
      assert(await page.locator("#play").isEnabled());
      assert(await page.locator("#disc-message").isVisible());
      for (const source of ["vinyl", "spotify", "plexamp", "dvd"]) {
        await page.locator("#source-" + source).click();
        await page.waitForFunction(
          (source) => document.body.dataset.source === source,
          source,
        );
        assert.equal(await page.locator("#track-section").isVisible(), false);
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          name + " " + source + " overflows",
        );
        if (source === "dvd")
          assert.equal(
            await page.locator("#dvd-subtitles").textContent(),
            "Nederlands · automatisch",
          );
        await page.screenshot({
          path: path.join(output, name + "-" + source + ".png"),
          fullPage: true,
        });
      }
      state = fixture("cd", true);
      await page.evaluate(() => readStatus());
      assert(await page.locator(".empty").isVisible());
      assert(await page.locator("#play").isDisabled());
      await page.screenshot({
        path: path.join(output, name + "-empty.png"),
        fullPage: true,
      });
      await page.locator("#theme-toggle").click();
      assert.equal(
        await page.locator("html").getAttribute("data-theme"),
        width > 760 ? "christmas" : "dark",
      );
      await page.screenshot({
        path: path.join(output, name + "-dark.png"),
        fullPage: true,
      });
      if (width > 760) {
        state = fixture("cd", false, true);
        await page.evaluate(() => readStatus());
        assert(await page.locator("#holiday-effects").isVisible());
        assert.equal(
          await page.locator("#holiday-effects").getAttribute("aria-pressed"),
          "true",
        );
        assert.equal(
          await page
            .locator(".christmas-snow")
            .evaluate((el) => getComputedStyle(el).display),
          "none",
          "Reduced motion must suppress snowfall",
        );
        await page.emulateMedia({ reducedMotion: "no-preference" });
        assert.equal(
          await page
            .locator(".christmas-snow")
            .evaluate((el) => getComputedStyle(el).display),
          "block",
        );
        assert.equal(await page.locator(".christmas-snow i").count(), 16);
        assert.equal(
          await page
            .locator(".christmas-hearth")
            .evaluate((el) => getComputedStyle(el).pointerEvents),
          "none",
        );
        await page.screenshot({
          path: path.join(output, name + "-christmas.png"),
          fullPage: true,
        });
        await page.locator("#holiday-effects").click();
        assert.equal(
          await page.locator("html").getAttribute("data-holiday-effects"),
          "off",
        );
        assert.equal(
          await page
            .locator(".christmas-snow")
            .evaluate((el) => getComputedStyle(el).display),
          "none",
        );
        await page.reload();
        await page.locator(".track-row").first().waitFor();
        assert.equal(
          await page.locator("html").getAttribute("data-holiday-effects"),
          "off",
          "Holiday preference must persist",
        );
        await page.locator("#holiday-effects").click();
        await page.setViewportSize({ width: 390, height: 844 });
        await page.waitForFunction(
          () => document.documentElement.dataset.theme === "dark",
        );
        assert.equal(await page.locator("#holiday-effects").isVisible(), false);
        assert.equal(
          await page.locator(".christmas-hearth").isVisible(),
          false,
        );
      }
      await context.close();
    }
    assert.deepEqual(failures, []);
    console.log(
      "Browser: three sizes, five sources, detached/empty CD, themes, focus and overflow passed. Synthetic data only.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
