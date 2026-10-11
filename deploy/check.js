// 올린 뒤 확인 — `python -m hanjang.smoke` 가 낸 JSON 을 받아 화면마다 상태와 스크립트 문법을 본다. 쓰는 법: deploy/check.sh
// 문제가 하나라도 있으면 실패(1)로 끝난다.
const fs = require("fs");
const pages = JSON.parse(fs.readFileSync(0, "utf8"));
let scripts = 0, bad = 0;
for (const [name, [status, body]] of Object.entries(pages)) {
  const notes = [];
  // /health 는 매일 실행이 밀렸을 때 503 을 낸다 — 화면이 깨진 게 아니라 알려 주는 것이라 여기선 내용만 보여 준다
  if (status !== "200" && name !== "/health") notes.push(`상태 ${status}${status === "500" ? " — " + body.slice(0, 120) : ""}`);
  if (name === "/health" && body !== "ok") notes.push(`「${body}」(매일 실행·디스크·DB 중 하나)`);
  let n = 0;
  if (name.endsWith(".js")) {
    n = 1;
    try { new Function(body); } catch (e) { notes.push(`문법 오류: ${e.message}`); }
  } else if (body.startsWith("<!DOCTYPE")) {
    const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
    let m;
    while ((m = re.exec(body))) {
      n++;
      try { new Function(m[1]); } catch (e) { notes.push(`${n}번째 스크립트 문법 오류: ${e.message}`); }
    }
    if (body.length < 2000) notes.push(`화면이 너무 작다(${body.length}자)`);
    if (/Traceback \(most recent call last\)/.test(body)) notes.push("화면에 오류 기록이 찍혔다");
  }
  scripts += n;
  const fail = notes.filter(x => !x.startsWith("「")).length;
  bad += fail;
  console.log(`${fail ? "✗" : "✓"} ${name.padEnd(22)} ${status} · 스크립트 ${n}개 · ${Math.round(body.length / 1024)}KB${notes.length ? " · " + notes.join(" · ") : ""}`);
}
console.log(`\n화면 ${Object.keys(pages).length}개 · 스크립트 ${scripts}개 · 문제 ${bad}개`);
process.exit(bad ? 1 : 0);
