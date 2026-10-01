// Open every page in headless Chrome: no console errors, every widget mounted, controls survive being used,
// no horizontal overflow at phone width. Usage: node tools/smoke.mjs [--shots]
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import fs from "node:fs";
const require = createRequire(process.env.HOME + "/apps/lms/package.json");
const puppeteer = require("puppeteer-core");
const PORT = 8765, shots = process.argv.includes("--shots");
const srv = spawn("python3", ["-m", "http.server", String(PORT), "-d", "dist"], { stdio: "ignore" });
await new Promise(r => setTimeout(r, 900));
const books = JSON.parse(fs.readFileSync("dist/books.json", "utf8"));
const paths = ["/"];
for (const b of books) { paths.push(`/${b.slug}/`); for (const c of JSON.parse(fs.readFileSync(`dist/${b.slug}/chapters.json`, "utf8"))) paths.push(`/${b.slug}/${c.slug}/`); }
const browser = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL", m); };
fs.mkdirSync("shots", { recursive: true });
for (const path of paths) {
  const page = await browser.newPage();
  const errs = [];
  page.on("pageerror", e => errs.push(e.message));
  page.on("console", m => { if (m.type() === "error" && !/fonts\.g|net::ERR/.test(m.text())) errs.push(m.text()); });
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`http://localhost:${PORT}${path}`, { waitUntil: "domcontentloaded" });
  await new Promise(r => setTimeout(r, 250));
  const r = await page.evaluate(() => {
    const out = { widgets: 0, unmounted: [], errs: [], used: 0 };
    document.querySelectorAll(".widget").forEach(w => {
      out.widgets++;
      if (w.querySelector(".w-err")) out.errs.push(w.dataset.widget + ": " + w.textContent.trim().slice(0, 90));
      else if (!w.children.length) out.unmounted.push(w.dataset.widget);
    });
    // use every control: sliders to both ends and the middle, every button twice
    document.querySelectorAll(".widget input[type=range]").forEach(i => {
      for (const f of [0, 1, 0.37]) { i.value = String(+i.min + (+i.max - +i.min) * f); i.dispatchEvent(new Event("input", { bubbles: true })); out.used++; }
    });
    for (let pass = 0; pass < 2; pass++) document.querySelectorAll(".widget button, .widget .steps li").forEach(b => { if (!b.disabled) { b.click(); out.used++; } });
    document.querySelectorAll(".widget input[type=text]").forEach(i => { i.value = "My PIN is 4821. I love jazz"; i.dispatchEvent(new Event("input", { bubbles: true })); });
    document.querySelectorAll(".widget").forEach(w => { if (w.querySelector(".w-err")) out.errs.push("after use " + w.dataset.widget); if (/NaN|undefined|Infinity/.test(w.textContent)) out.errs.push("bad number in " + w.dataset.widget); });
    return out;
  });
  await page.setViewport({ width: 380, height: 800 });
  await new Promise(r => setTimeout(r, 120));
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log(`${path}  widgets ${r.widgets}  controls used ${r.used}`);
  errs.forEach(e => fail(`${path} console: ${e}`));
  r.errs.forEach(e => fail(`${path} widget: ${e}`));
  r.unmounted.forEach(e => fail(`${path} not mounted: ${e}`));
  if (over > 1) fail(`${path} scrolls sideways by ${over}px at 380px`);
  if (shots) {
    const name = path === "/" ? "home" : path.replace(/^\/|\/$/g, "").replace(/\//g, "_");
    await page.screenshot({ path: `shots/${name}-phone.png` });
    await page.setViewport({ width: 1280, height: 900 });
    await page.reload({ waitUntil: "networkidle2" });
    await page.screenshot({ path: `shots/${name}.png` });
  }
  await page.close();
}
await browser.close(); srv.kill();
console.log(bad ? `${bad} problems` : "smoke: ok");
process.exit(bad ? 1 : 0);
