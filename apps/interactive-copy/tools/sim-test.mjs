import { createRequire } from "node:module";
import { spawn } from "node:child_process";
const require = createRequire(process.env.HOME + "/apps/lms/package.json");
const puppeteer = require("puppeteer-core");
const srv = spawn("python3", ["-m", "http.server", "8767", "-d", "dist"], { stdio: "ignore" });
await new Promise(r => setTimeout(r, 800));
const b = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const p = await b.newPage();
await p.goto("http://localhost:8767/23-the-memory-lab/", { waitUntil: "domcontentloaded" });
const out = await p.evaluate(() => {
  const w = document.querySelector("[data-widget=memory-sim]"), res = [];
  const click = (t) => [...w.querySelectorAll("button")].find(x => x.textContent.trim() === t).click();
  const box = () => [...w.querySelectorAll(".w-panel")].find(x => /The box/.test(x.textContent)).innerText;
  const desk = () => [...w.querySelectorAll(".w-panel")].find(x => /desk/i.test(x.querySelector("h5").textContent)).innerText;
  const log = () => [...w.querySelectorAll(".w-panel")].find(x => /What just happened/.test(x.textContent)).innerText;
  click("Play the whole script");
  res.push("BOX\n" + box(), "LOG\n" + log());
  for (const q of ["What should I cook for dinner?", "Any good bakeries near me?", "Where did I live before?", "Gift ideas for Sam?", "Suggest a snack for the school trip."]) { click(q); res.push("Q " + q + "\n" + desk()); }
  click("Let 30 days pass"); click("Let 30 days pass"); click("Let 30 days pass"); click("Run forget()");
  res.push("AFTER FORGET\n" + box() + "\n" + log().split("\n").slice(0, 4).join("\n"));
  const inp = w.querySelector("input[type=text]"); inp.value = "My sister thinks I should move to Rome. I'm allergic to shellfish. I'm vegetarian."; click("Remember");
  res.push("CUSTOM\n" + log().split("\n").slice(0, 8).join("\n"));
  return res.join("\n\n");
});
console.log(out);
await b.close(); srv.kill();
