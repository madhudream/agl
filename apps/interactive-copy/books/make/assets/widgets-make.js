/* The two example widgets of the guide. Copy one of them to start your own. */
(function () {
  "use strict";
  var MB = window.MB, F = MB.fmt, h = MB.h;

  // A calculator: sliders in, tiles and the arithmetic out. About 25 lines.
  MB.widget("coffee-cost", function (el, ui) {
    var st = {}, body = ui.frame("What does the coffee habit cost?", "Move a slider. Every number below is re-derived."), out = h("div");
    body.appendChild(ui.controls([
      { key: "cups", label: "Cups per day", min: 0, max: 8, value: 2 },
      { key: "price", label: "Price per cup", min: 0.5, max: 8, step: 0.1, value: 3.5, fmt: function (v) { return "$" + v.toFixed(2); } },
      { key: "years", label: "Years", min: 1, max: 40, value: 10 }
    ], st, draw));
    body.appendChild(out);
    function draw() {
      var day = st.cups * st.price, year = day * 365, total = year * st.years;
      out.textContent = "";
      out.appendChild(ui.tiles([
        { label: "Per day", value: F.usd(day) },
        { label: "Per year", value: F.usd(year) },
        { label: "Over " + st.years + " years", value: F.usd(total), kind: "hot" }]));
      out.appendChild(ui.calc([
        "per day    " + st.cups + " x $" + st.price.toFixed(2) + " = " + F.usd(day),
        "per year   " + F.usd(day) + " x 365 = " + F.usd(year),
        "total      " + F.usd(year) + " x " + st.years + " = " + F.usd(total)]));
      ui.foot(st.cups === 0 ? "No cups, no cost. Every slider should have a meaningful zero." : "The reader predicted a number before moving the slider. That is the whole trick.");
    }
    draw();
  });

  // A chart: one line, a hover layer, a marker for "now".
  MB.widget("savings-curve", function (el, ui) {
    var st = {}, body = ui.frame("The same money, invested", "A line chart with a marker. Hover to read a value."), out = h("div");
    body.appendChild(ui.controls([
      { key: "month", label: "Saved per month", min: 10, max: 1000, step: 10, value: 200, fmt: F.usd },
      { key: "rate", label: "Yearly return", min: 0, max: 12, step: 0.5, value: 5, fmt: function (v) { return v + "%"; } },
      { key: "at", label: "Look at year", min: 1, max: 40, value: 10 }
    ], st, draw));
    body.appendChild(out);
    function draw() {
      var a = [], b = [], y, v = 0, m;
      for (y = 0; y <= 40; y++) { a.push([y, st.month * 12 * y]); b.push([y, v]); for (m = 0; m < 12; m++) v = v * (1 + st.rate / 1200) + st.month; }
      out.textContent = "";
      out.appendChild(MB.lineChart({ series: [{ name: "Invested", points: b }, { name: "Under the mattress", points: a }], xLabel: "year", yLabel: "dollars",
        xMin: 0, xMax: 40, yFmt: F.usd, xFmt: String, marks: [{ x: st.at, label: "year " + st.at }], title: "savings over forty years" }));
      out.appendChild(ui.tiles([{ label: "Invested, year " + st.at, value: F.usd(b[st.at][1]), kind: "good" }, { label: "Mattress, year " + st.at, value: F.usd(a[st.at][1]) }]));
      ui.foot("One axis, two lines, a legend, direct labels at the line ends, and a hover layer. The engine draws all of it.");
    }
    draw();
  });
})();
