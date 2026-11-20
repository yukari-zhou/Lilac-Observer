(function charts() {
  "use strict";
  const ns = "http://www.w3.org/2000/svg";
  const money = (number) =>
    number.toLocaleString("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  const coord = (number) => number.toFixed(2);
  let observer;
  function element(tag, attrs, value) {
    const node = document.createElementNS(ns, tag);
    for (const [key, attr] of Object.entries(attrs || {}))
      node.setAttribute(key, String(attr));
    if (value !== undefined) node.textContent = value;
    return node;
  }
  window.mountIndexChart = function mountIndexChart(
    host,
    bars,
    range,
    analysis,
    intraday,
  ) {
    observer?.disconnect();
    if (!host) return;
    const minutes = range === "intraday";
    const intradayPoints = (intraday?.points || [])
      .filter((p) => /^\d{2}:\d{2}$/.test(p.time) && Number.isFinite(p.price) && p.price > 0)
      .map((p) => ({date: intraday.date, time: p.time, close: p.price}));
    const points = minutes ? intradayPoints : bars
      .filter(
        (b) =>
          Number.isFinite(b.close) &&
          b.close > 0 &&
          (!analysis.as_of || b.date <= analysis.as_of),
      )
      .slice(-range);
    if (!points.length) {
      const message = document.createElement("p");
      message.className = "empty";
      message.textContent = minutes ? "尚未取得该股的分时成交记录" : "尚无可绘制的收盘日线";
      host.replaceChildren(message);
      return;
    }
    let active = points.length - 1;
    let inspect = false;
    let schedule;
    function draw() {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (width < 120 || height < 100) return;
      const left = 9,
        right = width < 470 ? 61 : 73,
        top = 23,
        bottom = height - 29;
      const plotEnd = width - right;
      const projection =
        !minutes && analysis.status === "ok" &&
        points.at(-1).date === analysis.as_of &&
        ["low", "base", "high"].every((key) =>
          Number.isFinite(analysis.interval?.[key]),
        );
      const boundary = projection
        ? plotEnd - Math.max(43, (plotEnd - left) * 0.17)
        : plotEnd;
      const forecastX = plotEnd - 3;
      const prices = points.map((b) => b.close);
      if (projection)
        prices.push(analysis.interval.low, analysis.interval.high);
      const min = Math.min(...prices),
        max = Math.max(...prices);
      const stepTarget = Math.max((max - min) / 3.7, max * 0.00035);
      const scale = 10 ** Math.floor(Math.log10(stepTarget));
      const step =
        ([1, 2, 2.5, 5, 10].find((x) => x * scale >= stepTarget) || 10) * scale;
      const lo = Math.floor((min - step * 0.08) / step) * step;
      const hi = Math.ceil((max + step * 0.08) / step) * step;
      const y = (value) => top + ((hi - value) / (hi - lo)) * (bottom - top);
      const x = (i) =>
        points.length === 1
          ? boundary
          : left + ((boundary - left) * i) / (points.length - 1);
      const svg = element("svg", {
        viewBox: `0 0 ${width} ${height}`,
        class: "chart-svg",
        role: "img",
        tabindex: "0",
        "aria-label": minutes
          ? `${intraday.date} 分时股价，${points[0].time} 至 ${points.at(-1).time}。使用左右方向键查看记录。`
          : `收盘走势，${points[0].date} 至 ${points.at(-1).date}。使用左右方向键查看逐日行情。`,
      });
      const nodes = (tag, attrs, value) => {
        const n = element(tag, attrs, value);
        svg.append(n);
        return n;
      };
      const defs = nodes("defs");
      const gradient = element("linearGradient", {
        id: "under",
        x1: "0",
        x2: "0",
        y1: "0",
        y2: "1",
      });
      gradient.append(
        element("stop", {
          offset: "0%",
          "stop-color": "#477f66",
          "stop-opacity": 0.27,
        }),
        element("stop", {
          offset: "100%",
          "stop-color": "#477f66",
          "stop-opacity": 0.015,
        }),
      );
      defs.append(gradient);
      for (let tick = lo; tick <= hi + step * 0.01; tick += step) {
        nodes("line", {
          x1: left,
          x2: plotEnd,
          y1: y(tick),
          y2: y(tick),
          stroke: "#b6c1b2",
          "stroke-dasharray": "3 5",
          "stroke-width": 0.8,
        });
        nodes(
          "text",
          { x: width - 4, y: y(tick) + 4, "text-anchor": "end" },
          tick.toLocaleString("zh-CN", { maximumFractionDigits: Math.min(4, Math.max(1, 1 - Math.floor(Math.log10(step)))) }),
        );
      }
      const axisLabels = width < 460 ? 3 : 5;
      for (let i = 0; i < axisLabels; i++) {
        const pos = Math.round(((points.length - 1) * i) / (axisLabels - 1));
        if (
          points.length < axisLabels &&
          i > 0 &&
          pos === Math.round(((points.length - 1) * (i - 1)) / (axisLabels - 1))
        )
          continue;
        nodes(
          "text",
          {
            x: x(pos),
            y: height - 7,
            "text-anchor":
              i === 0 ? "start" : i === axisLabels - 1 ? "end" : "middle",
          },
          minutes ? points[pos].time : points[pos].date.slice(5),
        );
      }
      const line = points
        .map((b, i) => `${i ? "L" : "M"}${coord(x(i))},${coord(y(b.close))}`)
        .join(" ");
      nodes("path", {
        d: `${line} L${coord(boundary)},${bottom} L${coord(x(0))},${bottom} Z`,
        fill: "url(#under)",
      });
      nodes("path", {
        d: line,
        fill: "none",
        stroke: "#226649",
        "stroke-width": 2.35,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
      });
      const lastY = y(points.at(-1).close);
      if (projection) {
        const { low, high, base } = analysis.interval;
        nodes("rect", {
          x: boundary,
          y: top,
          width: plotEnd - boundary,
          height: bottom - top,
          fill: "#a88749",
          "fill-opacity": 0.032,
        });
        nodes("line", {
          x1: boundary,
          x2: boundary,
          y1: top,
          y2: bottom,
          stroke: "#95815f",
          "stroke-dasharray": "3 5",
        });
        nodes("path", {
          d: `M${boundary} ${lastY} L${forecastX} ${y(high)} L${forecastX} ${y(low)} Z`,
          fill: "#bd9757",
          "fill-opacity": 0.17,
          stroke: "#97743f",
          "stroke-opacity": 0.46,
          "stroke-width": 1,
        });
        nodes("line", {
          x1: boundary,
          x2: forecastX,
          y1: lastY,
          y2: y(base),
          stroke: "#856532",
          "stroke-width": 1.6,
          "stroke-dasharray": "4 3",
        });
        nodes("circle", { cx: forecastX, cy: y(base), r: 3, fill: "#997841" });
        nodes(
          "text",
          { x: forecastX, y: height - 7, "text-anchor": "end" },
          `+${analysis.horizon}日`,
        );
      }
      nodes("circle", {
        cx: boundary,
        cy: lastY,
        r: 3.4,
        fill: "#376b54",
        stroke: "#fffef9",
        "stroke-width": 1.5,
      });
      const hair = nodes("line", {
        y1: top,
        y2: bottom,
        stroke: "#738575",
        "stroke-dasharray": "3 3",
        visibility: "hidden",
      });
      const dot = nodes("circle", {
        r: 4,
        fill: "#fffef9",
        stroke: "#306047",
        "stroke-width": 2,
        visibility: "hidden",
      });
      const tip = document.createElement("div");
      tip.className = "chart-tip";
      tip.setAttribute("role", "status");
      const show = (i) => {
        active = Math.max(0, Math.min(points.length - 1, i));
        inspect = true;
        const bar = points[active],
          px = x(active),
          py = y(bar.close);
        hair.setAttribute("x1", px);
        hair.setAttribute("x2", px);
        hair.setAttribute("visibility", "visible");
        dot.setAttribute("cx", px);
        dot.setAttribute("cy", py);
        dot.setAttribute("visibility", "visible");
        tip.replaceChildren();
        const date = document.createElement("b");
        date.textContent = minutes ? `${bar.date} ${bar.time}` : bar.date;
        tip.append(
          date,
          document.createElement("br"),
          minutes ? `股价 ${money(bar.close)} 元` : `收盘 ${money(bar.close)}`,
        );
        if (Number.isFinite(bar.high) && Number.isFinite(bar.low))
          tip.append(
            document.createElement("br"),
            `低 ${money(bar.low)} · 高 ${money(bar.high)}`,
          );
        tip.style.display = "block";
        tip.style.left = `${Math.max(3, Math.min(width - tip.offsetWidth - 3, px > width * 0.58 ? px - tip.offsetWidth - 12 : px + 12))}px`;
        tip.style.top = `${Math.max(3, Math.min(height - tip.offsetHeight - 6, py - tip.offsetHeight / 2))}px`;
      };
      const hide = () => {
        inspect = false;
        hair.setAttribute("visibility", "hidden");
        dot.setAttribute("visibility", "hidden");
        tip.style.display = "none";
      };
      svg.addEventListener("pointermove", (e) => {
        const px = e.clientX - svg.getBoundingClientRect().left;
        if (px > boundary + 8) hide();
        else
          show(
            Math.round(((px - left) / (boundary - left)) * (points.length - 1)),
          );
      });
      svg.addEventListener("pointerleave", hide);
      svg.addEventListener("focus", () => show(active));
      svg.addEventListener("blur", hide);
      svg.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          show(active + (e.key === "ArrowRight" ? 1 : -1));
        }
      });
      host.replaceChildren(svg, tip);
      if (inspect) show(active);
    }
    draw();
    observer = new ResizeObserver(() => {
      cancelAnimationFrame(schedule);
      schedule = requestAnimationFrame(draw);
    });
    observer.observe(host);
  };
})();
