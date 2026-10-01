// node tools/shot.mjs <path> <out.png> [selector] [dark] [width]
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
const require = createRequire(process.env.HOME + "/apps/lms/package.json");
const puppeteer = require("puppeteer-core");
const [path, out, sel, dark, width] = process.argv.slice(2);
const srv = spawn("python3", ["-m", "http.server", "8766", "-d", "dist"], { stdio: "ignore" });
await new Promise(r => setTimeout(r, 800));
const b = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const p = await b.newPage();
await p.setViewport({ width: +(width || 1280), height: 1000, deviceScaleFactor: 1 });
if (dark === "dark") await p.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "dark" }]);
await p.goto("http://localhost:8766" + path, { waitUntil: "networkidle2" });
if (sel && sel !== "-") { const el = await p.$(sel); await el.scrollIntoView(); await el.screenshot({ path: out }); } else await p.screenshot({ path: out });
await b.close(); srv.kill();
