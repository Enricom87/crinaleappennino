// Crinale · bot Telegram per gli avvisi personali.
// Gira su Cloudflare Workers (gratuito). Legge i dati pubblici del sito (api/v1/bot.json) e manda a
// ogni iscritto solo gli avvisi delle località che segue. Conserva soltanto: id della chat Telegram,
// lingua e località seguite (KV "SUBS"). Con /stop si cancella tutto.

const SITE = "https://crinaleappennino.it";
const FEED = SITE + "/api/v1/bot.json";
const LANGS = ["it", "en", "de", "fr", "es", "zh"];
const CHANNEL = "@crinaleappennino";

const M = {
  it: {
    hi: "Ciao! Sono il bot di <b>Crinale</b> ⛰️\nScegli le località che ti interessano: ti scrivo solo quando c'è qualcosa da sapere (neve in arrivo, il weekend che cambia) e ogni giovedì sera il verdetto del weekend.",
    pick: "Tocca una località per seguirla o smettere di seguirla:",
    list: "Segui:", none: "Non segui ancora nessuna località. Scrivi /segui per sceglierle.",
    stop: "Fatto: ho cancellato le tue preferenze e non ti scriverò più. Per ricominciare scrivi /start.",
    added: "Ora segui {n} ✅", removed: "Non segui più {n}",
    alert: "❄️ <b>{n}</b>\n{t}", wkchg: "🔄 <b>Il weekend a {n} è cambiato</b>\n{w}\n{a}",
    thu: "📅 <b>Il verdetto del weekend</b>", open: "Apri la previsione",
    help: "Comandi: /segui per scegliere le località · /lista per vedere cosa segui · /stop per cancellarti.",
  },
  en: {
    hi: "Hi! I'm the <b>Crinale</b> bot ⛰️\nPick the places you care about: I'll only write when there's something worth knowing (snow on the way, the weekend changing), plus the weekend verdict every Thursday evening.",
    pick: "Tap a place to follow or unfollow it:",
    list: "Following:", none: "You're not following any place yet. Send /segui to pick some.",
    stop: "Done: I deleted your preferences and won't write again. Send /start to begin again.",
    added: "Now following {n} ✅", removed: "No longer following {n}",
    alert: "❄️ <b>{n}</b>\n{t}", wkchg: "🔄 <b>The weekend at {n} has changed</b>\n{w}\n{a}",
    thu: "📅 <b>Weekend verdict</b>", open: "Open the forecast",
    help: "Commands: /segui to pick places · /lista to see what you follow · /stop to unsubscribe.",
  },
  de: {
    hi: "Hallo! Ich bin der <b>Crinale</b>-Bot ⛰️\nWähle deine Orte: Ich schreibe nur, wenn es etwas Wichtiges gibt (Schnee im Anmarsch, das Wochenende ändert sich), und jeden Donnerstagabend das Wochenend-Urteil.",
    pick: "Tippe auf einen Ort, um ihm zu folgen oder nicht mehr zu folgen:",
    list: "Du folgst:", none: "Du folgst noch keinem Ort. Schreib /segui, um welche zu wählen.",
    stop: "Erledigt: Deine Einstellungen sind gelöscht, ich schreibe nicht mehr. Mit /start geht's wieder los.",
    added: "Du folgst jetzt {n} ✅", removed: "Du folgst {n} nicht mehr",
    alert: "❄️ <b>{n}</b>\n{t}", wkchg: "🔄 <b>Das Wochenende in {n} hat sich geändert</b>\n{w}\n{a}",
    thu: "📅 <b>Das Wochenend-Urteil</b>", open: "Vorhersage öffnen",
    help: "Befehle: /segui Orte wählen · /lista was du folgst · /stop abmelden.",
  },
  fr: {
    hi: "Salut ! Je suis le bot de <b>Crinale</b> ⛰️\nChoisis tes stations : je t'écris seulement quand il y a du nouveau (neige en approche, week-end qui change), et chaque jeudi soir le verdict du week-end.",
    pick: "Touche une station pour la suivre ou ne plus la suivre :",
    list: "Tu suis :", none: "Tu ne suis encore aucune station. Envoie /segui pour en choisir.",
    stop: "C'est fait : tes préférences sont effacées, je ne t'écrirai plus. Envoie /start pour recommencer.",
    added: "Tu suis maintenant {n} ✅", removed: "Tu ne suis plus {n}",
    alert: "❄️ <b>{n}</b>\n{t}", wkchg: "🔄 <b>Le week-end à {n} a changé</b>\n{w}\n{a}",
    thu: "📅 <b>Le verdict du week-end</b>", open: "Ouvrir la prévision",
    help: "Commandes : /segui choisir les stations · /lista voir ce que tu suis · /stop se désinscrire.",
  },
  es: {
    hi: "¡Hola! Soy el bot de <b>Crinale</b> ⛰️\nElige tus sitios: solo te escribo cuando hay algo que saber (nieve en camino, el fin de semana cambia) y cada jueves por la tarde el veredicto del fin de semana.",
    pick: "Toca un sitio para seguirlo o dejar de seguirlo:",
    list: "Sigues:", none: "Aún no sigues ningún sitio. Escribe /segui para elegirlos.",
    stop: "Hecho: he borrado tus preferencias y no te escribiré más. Escribe /start para empezar de nuevo.",
    added: "Ahora sigues {n} ✅", removed: "Ya no sigues {n}",
    alert: "❄️ <b>{n}</b>\n{t}", wkchg: "🔄 <b>El fin de semana en {n} ha cambiado</b>\n{w}\n{a}",
    thu: "📅 <b>El veredicto del fin de semana</b>", open: "Abrir la previsión",
    help: "Comandos: /segui elegir sitios · /lista ver lo que sigues · /stop darte de baja.",
  },
  zh: {
    hi: "你好！我是 <b>Crinale</b> 机器人 ⛰️\n选择你关注的地点：只有在值得知道时我才会发消息（即将降雪、周末天气变化），每周四晚上发送周末结论。",
    pick: "点按地点即可关注或取消关注：",
    list: "已关注：", none: "你还没有关注任何地点。发送 /segui 进行选择。",
    stop: "已完成：你的偏好已删除，我不会再发消息。发送 /start 重新开始。",
    added: "已关注 {n} ✅", removed: "已取消关注 {n}",
    alert: "❄️ <b>{n}</b>\n{t}", wkchg: "🔄 <b>{n} 的周末情况有变</b>\n{w}\n{a}",
    thu: "📅 <b>周末结论</b>", open: "打开预报",
    help: "命令：/segui 选择地点 · /lista 查看已关注 · /stop 退订。",
  },
};
const DOT = { green: "🟢", yellow: "🟡", red: "🔴" };
const ORIGINS = ["https://crinaleappennino.it", "https://www.crinaleappennino.it"];
const cors = (req) => ({
  "Access-Control-Allow-Origin": ORIGINS.includes(req.headers.get("Origin")) ? req.headers.get("Origin") : ORIGINS[0],
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "content-type",
});
const clip = (v, n) => String(v ?? "").replace(/[\u0000-\u001f]/g, " ").trim().slice(0, n);
const isDate = (d) => /^\d{4}-\d{2}-\d{2}$/.test(d) && !isNaN(Date.parse(d));

// --- Segnalazione eventi: arrivano dal modulo del sito, li approvi tu su Telegram -----------------
async function submitEvent(req, env) {
  const h = cors(req);
  let b;
  try { b = await req.json(); } catch { return Response.json({ ok: false, err: "json" }, { status: 400, headers: h }); }
  if (b.website) return Response.json({ ok: true }, { headers: h }); // trappola per i bot di spam
  const ev = {
    title: clip(b.title, 120), from: clip(b.from, 10), to: clip(b.to || b.from, 10), loc: clip(b.loc, 40),
    place: clip(b.place, 120), desc: clip(b.desc, 600), url: clip(b.url, 300), org: clip(b.org, 120),
    contact: clip(b.contact, 160), lang: LANGS.includes(b.lang) ? b.lang : "it",
  };
  const today = new Date().toISOString().slice(0, 10);
  if (!ev.title || !isDate(ev.from) || !isDate(ev.to) || ev.to < ev.from || ev.to < today || !ev.loc || !ev.contact)
    return Response.json({ ok: false, err: "campi" }, { status: 400, headers: h });
  if (ev.url && !/^https?:\/\//.test(ev.url)) ev.url = "https://" + ev.url;
  const ip = req.headers.get("CF-Connecting-IP") || "x";
  const rk = `rl:${ip}:${today}`;
  const n = +(await env.SUBS.get(rk) || 0);
  if (n >= 5) return Response.json({ ok: false, err: "troppe" }, { status: 429, headers: h });
  await env.SUBS.put(rk, String(n + 1), { expirationTtl: 86400 });
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  await env.SUBS.put("evp:" + id, JSON.stringify(ev), { expirationTtl: 60 * 86400 });
  const admin = await env.SUBS.get("admin");
  if (admin) {
    const when = ev.from === ev.to ? ev.from : `${ev.from} → ${ev.to}`;
    await tg(env, "sendMessage", { chat_id: admin, parse_mode: "HTML", disable_web_page_preview: true,
      text: `🎟️ <b>Nuovo evento da approvare</b>\n\n<b>${esc(ev.title)}</b>\n📅 ${when}\n📍 ${esc(ev.place)} (${esc(ev.loc)})\n\n${esc(ev.desc)}\n\n🔗 ${esc(ev.url)}\n👤 ${esc(ev.org)} · ${esc(ev.contact)}`,
      reply_markup: { inline_keyboard: [[{ text: "✅ Approva", callback_data: "ea:" + id }, { text: "❌ Rifiuta", callback_data: "er:" + id }]] } });
  }
  return Response.json({ ok: true }, { headers: h });
}

// --- Segnala la neve: osservazioni dal territorio, pubblicate subito, rimovibili dall'amministratore ---
const KINDS = ["nevica", "neve", "pioggia", "niente"];
async function submitReport(req, env) {
  const h = cors(req);
  let b;
  try { b = await req.json(); } catch { return Response.json({ ok: false }, { status: 400, headers: h }); }
  if (b.website) return Response.json({ ok: true }, { headers: h });
  const r = { loc: clip(b.loc, 40), kind: KINDS.includes(b.kind) ? b.kind : "", elev: Math.round(+b.elev || 0),
              cm: Math.max(0, Math.min(400, Math.round(+b.cm || 0))), note: clip(b.note, 200), place: clip(b.place, 80),
              ts: new Date().toISOString() };
  if (!r.loc || !r.kind || r.elev < 200 || r.elev > 2200) return Response.json({ ok: false, err: "campi" }, { status: 400, headers: h });
  const ip = req.headers.get("CF-Connecting-IP") || "x";
  const rk = `rlr:${ip}:${r.ts.slice(0, 13)}`;
  const n = +(await env.SUBS.get(rk) || 0);
  if (n >= 4) return Response.json({ ok: false, err: "troppe" }, { status: 429, headers: h });
  await env.SUBS.put(rk, String(n + 1), { expirationTtl: 7200 });
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  await env.SUBS.put("rep:" + id, JSON.stringify({ id, ...r }), { expirationTtl: 4 * 86400 });
  const admin = await env.SUBS.get("admin");
  if (admin) {
    const what = { nevica: "❄️ nevica", neve: "⛄ neve al suolo", pioggia: "🌧️ pioggia", niente: "🟫 niente neve" }[r.kind];
    await tg(env, "sendMessage", { chat_id: admin, parse_mode: "HTML",
      text: `📍 <b>Segnalazione</b> ${esc(r.loc)} · ${esc(r.place)} ${r.elev} m\n${what}${r.cm ? ` · ${r.cm} cm` : ""}\n${esc(r.note)}`,
      reply_markup: { inline_keyboard: [[{ text: "🗑️ Rimuovi", callback_data: "rr:" + id }]] } });
  }
  return Response.json({ ok: true, id }, { headers: h });
}

async function listReports(req, env) {
  const url = new URL(req.url);
  const loc = url.searchParams.get("loc");
  const out = [];
  let cursor;
  do {
    const page = await env.SUBS.list({ prefix: "rep:", cursor });
    for (const k of page.keys) {
      const v = await env.SUBS.get(k.name);
      if (!v) continue;
      const r = JSON.parse(v);
      if (!loc || r.loc === loc) out.push(r);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  out.sort((a, b) => (a.ts < b.ts ? 1 : -1));
  return Response.json({ reports: out.slice(0, 50) }, { headers: { ...cors(req), "Access-Control-Allow-Origin": "*", "cache-control": "no-store" } });
}

async function removeReport(env, cq) {
  const admin = await env.SUBS.get("admin");
  if (String(cq.message.chat.id) !== admin) return tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
  await env.SUBS.delete("rep:" + cq.data.slice(3));
  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: "Rimossa" });
  return tg(env, "editMessageText", { chat_id: cq.message.chat.id, message_id: cq.message.message_id,
    text: (cq.message.text || "") + "\n\n🗑️ Rimossa" });
}

async function moderate(env, cq) {
  const id = cq.data.slice(3), ok = cq.data.startsWith("ea:");
  const admin = await env.SUBS.get("admin");
  if (String(cq.message.chat.id) !== admin) return tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
  const raw = await env.SUBS.get("evp:" + id);
  let note = "Già gestito";
  if (raw) {
    const ev = JSON.parse(raw);
    if (ok) {
      const ttl = Math.max(86400, Math.round((Date.parse(ev.to) - Date.now()) / 1000) + 2 * 86400);
      const { contact, ...pub } = ev; // il contatto resta privato: non va sul sito
      await env.SUBS.put("evok:" + id, JSON.stringify({ id, ...pub }), { expirationTtl: ttl });
      // annuncio anche sul canale pubblico
      const when = ev.from === ev.to ? ev.from.split("-").reverse().join("/") : ev.from.split("-").reverse().join("/") + " → " + ev.to.split("-").reverse().join("/");
      await tg(env, "sendMessage", { chat_id: CHANNEL, parse_mode: "HTML", disable_web_page_preview: true,
        text: `🎟️ <b>${esc(ev.title)}</b>\n📅 ${when} · 📍 ${esc(ev.place || ev.loc)}\n${esc(ev.desc).slice(0, 400)}` + (ev.url ? `\n🔗 ${esc(ev.url)}` : "") });
    }
    await env.SUBS.delete("evp:" + id);
    note = ok ? "✅ Approvato: sarà sul sito al prossimo aggiornamento" : "❌ Rifiutato";
  }
  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: note });
  return tg(env, "editMessageText", { chat_id: cq.message.chat.id, message_id: cq.message.message_id,
    parse_mode: "HTML", text: (cq.message.text || "").slice(0, 3500) + "\n\n<b>" + note + "</b>" });
}

// ---------- Facebook: bozze preparate dalla pipeline, pubblicate solo dopo l'ok dell'amministratore ----------
const FB_API = "https://graph.facebook.com/v21.0";

async function fbDraft(req, env) {
  if (req.headers.get("X-Secret") !== (await secretOf(env))) return new Response("no", { status: 403 });
  const admin = await env.SUBS.get("admin");
  if (!admin) return new Response("nessun amministratore: manda /admin al bot", { status: 409 });
  const { text, link, kind } = await req.json();
  const id = Date.now().toString(36);
  await env.SUBS.put("fbd:" + id, JSON.stringify({ text: String(text || "").slice(0, 5000), link: link || "", kind: kind || "" }), { expirationTtl: 3 * 86400 });
  await fbAsk(env, admin, id, text, link);
  return new Response("ok");
}

async function fbAsk(env, chat, id, text, link) {
  const ready = !!(env.FB_PAGE_TOKEN && env.FB_PAGE_ID);
  return tg(env, "sendMessage", { chat_id: chat, link_preview_options: { is_disabled: true },
    text: "📘 Bozza per la pagina Facebook" + (ready ? "" : " (Facebook non ancora collegato: copiala a mano)") +
      ":\n\n" + String(text || "").slice(0, 3600) + (link ? "\n\n🔗 " + link : "") +
      "\n\n✏️ Per modificarla rispondi a questo messaggio con il testo nuovo.\n#fb" + id,
    reply_markup: { inline_keyboard: [[{ text: "✅ Pubblica", callback_data: "fp:" + id }, { text: "❌ Scarta", callback_data: "fx:" + id }]] } });
}

async function fbDecide(env, cq) {
  const admin = await env.SUBS.get("admin");
  if (String(cq.message.chat.id) !== admin) return tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
  const id = cq.data.slice(3), go = cq.data.startsWith("fp:");
  const raw = await env.SUBS.get("fbd:" + id);
  let note = "Già gestita";
  if (raw) {
    const d = JSON.parse(raw);
    if (go) {
      if (!(env.FB_PAGE_TOKEN && env.FB_PAGE_ID)) note = "Facebook non collegato";
      else {
        const body = new URLSearchParams({ message: d.text, access_token: env.FB_PAGE_TOKEN });
        if (d.link) body.set("link", d.link);
        const r = await fetch(`${FB_API}/${env.FB_PAGE_ID}/feed`, { method: "POST", body });
        const j = await r.json().catch(() => ({}));
        note = r.ok && j.id ? "✅ Pubblicato su Facebook" : "⚠️ Facebook ha rifiutato: " + ((j.error && j.error.message) || r.status);
        if (r.ok && j.id) await env.SUBS.delete("fbd:" + id);
      }
    } else { await env.SUBS.delete("fbd:" + id); note = "❌ Scartata"; }
  }
  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: note.slice(0, 190) });
  return tg(env, "editMessageText", { chat_id: cq.message.chat.id, message_id: cq.message.message_id,
    link_preview_options: { is_disabled: true }, text: (cq.message.text || "").slice(0, 3800) + "\n\n" + note });
}

async function fbEdit(env, msg) {
  // l'amministratore risponde alla bozza con il testo corretto: si aggiorna e si richiede l'ok
  const m = /#fb([a-z0-9]+)/.exec((msg.reply_to_message && msg.reply_to_message.text) || "");
  if (!m) return false;
  const admin = await env.SUBS.get("admin");
  if (String(msg.chat.id) !== admin) return false;
  const raw = await env.SUBS.get("fbd:" + m[1]);
  if (!raw) { await tg(env, "sendMessage", { chat_id: msg.chat.id, text: "Bozza scaduta o già gestita." }); return true; }
  const d = { ...JSON.parse(raw), text: msg.text.slice(0, 5000) };
  await env.SUBS.put("fbd:" + m[1], JSON.stringify(d), { expirationTtl: 3 * 86400 });
  await fbAsk(env, msg.chat.id, m[1], d.text, d.link);
  return true;
}

async function listEvents(req, env) {
  const out = [];
  let cursor;
  do {
    const page = await env.SUBS.list({ prefix: "evok:", cursor });
    for (const k of page.keys) { const v = await env.SUBS.get(k.name); if (v) out.push(JSON.parse(v)); }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return Response.json({ events: out }, { headers: { ...cors(req), "cache-control": "no-store" } });
}

const fmt = (s, o) => s.replace(/\{(\w)\}/g, (_, k) => o[k] ?? "");
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const langOf = (code) => { const l = (code || "it").slice(0, 2).toLowerCase(); return LANGS.includes(l) ? l : "en"; };

async function secretOf(env) {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("crinale:" + env.TELEGRAM_BOT_TOKEN));
  return [...new Uint8Array(h)].slice(0, 20).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json();
}

async function feed() {
  const r = await fetch(FEED + "?t=" + Date.now(), { cf: { cacheTtl: 0 } });
  return r.json();
}

const getUser = async (env, id) => JSON.parse((await env.SUBS.get("u:" + id)) || "null");
const putUser = (env, id, u) => env.SUBS.put("u:" + id, JSON.stringify(u));

function keyboard(data, u) {
  const rows = [];
  let row = [];
  for (const L of data.locs) {
    const on = u.locs.includes(L.slug);
    const name = (L.i18n[u.lang] || L.i18n.it).name.split(" · ")[0];
    row.push({ text: (on ? "✅ " : "▫️ ") + name, callback_data: "t:" + L.slug });
    if (row.length === 2) { rows.push(row); row = []; }
  }
  if (row.length) rows.push(row);
  return { inline_keyboard: rows };
}

function listText(data, u) {
  const t = M[u.lang];
  const names = data.locs.filter((L) => u.locs.includes(L.slug)).map((L) => "• " + esc((L.i18n[u.lang] || L.i18n.it).name));
  return names.length ? t.list + "\n" + names.join("\n") : t.none;
}

async function onMessage(env, msg) {
  const id = msg.chat.id;
  const text = (msg.text || "").trim();
  const data = await feed();
  let u = (await getUser(env, id)) || { lang: langOf(msg.from && msg.from.language_code), locs: [], sig: {} };
  const t = M[u.lang];
  const [cmd, arg] = text.split(/\s+/);
  const c = cmd.split("@")[0].toLowerCase();
  if (c === "/admin") {
    const cur = await env.SUBS.get("admin");
    if (!cur) { await env.SUBS.put("admin", String(id)); return tg(env, "sendMessage", { chat_id: id, text: "✅ Sei l'amministratore: qui riceverai gli eventi da approvare." }); }
    return tg(env, "sendMessage", { chat_id: id, text: cur === String(id) ? "Sei già l'amministratore ✅" : t.help });
  }
  if (c === "/stop") {
    await env.SUBS.delete("u:" + id);
    return tg(env, "sendMessage", { chat_id: id, text: t.stop });
  }
  if (c === "/start") {
    const slug = (arg || "").replace(/[^a-z0-9-]/g, "");
    const L0 = data.locs.find((L) => L.slug === slug);
    if (L0 && !u.locs.includes(slug)) {
      u.locs.push(slug);
      u.sig = u.sig || {};
      u.sig[slug] = { lv: L0.level === "alert" ? L0.i18n.it.title : "", wk: L0.wk_color };
    }
    await putUser(env, id, u);
    return tg(env, "sendMessage", { chat_id: id, parse_mode: "HTML", text: t.hi + "\n\n" + t.pick,
      reply_markup: keyboard(data, u) });
  }
  if (c === "/segui" || c === "/follow") {
    await putUser(env, id, u);
    return tg(env, "sendMessage", { chat_id: id, text: t.pick, reply_markup: keyboard(data, u) });
  }
  if (c === "/lista" || c === "/list") {
    return tg(env, "sendMessage", { chat_id: id, parse_mode: "HTML", text: listText(data, u) });
  }
  return tg(env, "sendMessage", { chat_id: id, text: t.help });
}

async function onCallback(env, cq) {
  if (/^e[ar]:/.test(cq.data || "")) return moderate(env, cq);
  if (/^rr:/.test(cq.data || "")) return removeReport(env, cq);
  if (/^f[bpx]:/.test(cq.data || "")) return fbDecide(env, cq);
  const id = cq.message.chat.id;
  const slug = (cq.data || "").slice(2);
  const data = await feed();
  const L = data.locs.find((x) => x.slug === slug);
  let u = (await getUser(env, id)) || { lang: langOf(cq.from && cq.from.language_code), locs: [], sig: {} };
  if (!L) return tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
  const name = (L.i18n[u.lang] || L.i18n.it).name.split(" · ")[0];
  let note;
  if (u.locs.includes(slug)) { u.locs = u.locs.filter((s) => s !== slug); note = fmt(M[u.lang].removed, { n: name }); }
  else { u.locs.push(slug); note = fmt(M[u.lang].added, { n: name }); }
  // registra lo stato attuale, così il primo avviso arriva solo quando qualcosa cambia davvero
  u.sig = u.sig || {};
  u.sig[slug] = { lv: L.level === "alert" ? L.i18n.it.title : "", wk: L.wk_color };
  await putUser(env, id, u);
  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: note });
  return tg(env, "editMessageReplyMarkup", { chat_id: id, message_id: cq.message.message_id, reply_markup: keyboard(data, u) });
}

function romeNow() {
  const p = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Rome", weekday: "short", hour: "2-digit",
    year: "numeric", month: "2-digit", day: "2-digit", hour12: false }).formatToParts(new Date());
  const g = (t) => p.find((x) => x.type === t).value;
  return { wd: g("weekday"), hour: +g("hour"), day: `${g("year")}-${g("month")}-${g("day")}` };
}

async function notifyAll(env) {
  const data = await feed();
  const now = romeNow();
  const thursday = now.wd === "Thu" && now.hour >= 18;
  let cursor;
  do {
    const page = await env.SUBS.list({ prefix: "u:", cursor });
    for (const k of page.keys) {
      const id = k.name.slice(2);
      const u = await getUser(env, id);
      if (!u || !u.locs.length) continue;
      const t = M[u.lang] || M.it;
      u.sig = u.sig || {};
      let changed = false;
      const thuLines = [];
      for (const L of data.locs.filter((x) => u.locs.includes(x.slug))) {
        const x = L.i18n[u.lang] || L.i18n.it;
        const prev = u.sig[L.slug] || {};
        const lv = L.level === "alert" ? L.i18n.it.title : "";
        const btn = { reply_markup: { inline_keyboard: [[{ text: t.open, url: x.url }]] } };
        if (lv && lv !== prev.lv && !data.summer) {
          await tg(env, "sendMessage", { chat_id: id, parse_mode: "HTML", text: fmt(t.alert, { n: esc(x.name), t: esc(x.title) }), ...btn });
        } else if (!thursday && prev.wk && L.wk_color && prev.wk !== L.wk_color) {
          await tg(env, "sendMessage", { chat_id: id, parse_mode: "HTML", ...btn,
            text: fmt(t.wkchg, { n: esc(x.name.split(" · ")[0]), w: (DOT[L.wk_color] || "") + " " + esc(x.wk_title), a: esc(x.wk_advice) }) });
        }
        if (thursday && L.wk_color) {
          thuLines.push(`${DOT[L.wk_color]} <b>${esc(x.name.split(" · ")[0])}</b>: ${esc(x.wk_title)}\n<i>${esc(x.wk_days.join(" · "))}</i>`);
        }
        if (prev.lv !== lv || prev.wk !== L.wk_color) { u.sig[L.slug] = { lv, wk: L.wk_color }; changed = true; }
      }
      if (thursday && thuLines.length && u.thu !== now.day) {
        await tg(env, "sendMessage", { chat_id: id, parse_mode: "HTML", disable_web_page_preview: true,
          text: t.thu + "\n\n" + thuLines.join("\n\n") });
        u.thu = now.day; changed = true;
      }
      if (changed) await putUser(env, id, u);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
}


// Aggiornamento del sito appena esce una nuova corsa europea (principale o scenari) su Open-Meteo:
// ogni 10 minuti confronta l'orario di uscita con l'ultimo visto e, se è cambiato, fa partire il giro su GitHub.
// Serve il segreto GH_DISPATCH_TOKEN (token GitHub con permesso Actions: lettura e scrittura su questo repository).
const RUN_META = {
  ecmwf: "https://api.open-meteo.com/data/ecmwf_ifs025/static/meta.json",
  ens: "https://ensemble-api.open-meteo.com/data/ecmwf_ifs025_ensemble/static/meta.json",
};
const MIN_GAP_MIN = 120; // al massimo un giro ogni 2 ore: rispetta i limiti del servizio gratuito
async function checkRuns(env) {
  if (!env.GH_DISPATCH_TOKEN) return;
  const seen = JSON.parse((await env.SUBS.get("runs_seen")) || "{}");
  const now = {};
  for (const [k, u] of Object.entries(RUN_META)) {
    try { const j = await (await fetch(u, { cf: { cacheTtl: 0 } })).json(); now[k] = j.last_run_availability_time; } catch (e) { /* riprova al prossimo giro */ }
  }
  const changed = Object.keys(now).filter(k => now[k] && now[k] !== seen[k]);
  if (!changed.length) return;
  const last = +((await env.SUBS.get("runs_last_dispatch")) || 0);
  if (Date.now() - last < MIN_GAP_MIN * 60000) return; // non segno come visto: partirà al prossimo controllo utile
  const r = await fetch("https://api.github.com/repos/Enricom87/crinaleappennino/actions/workflows/update.yml/dispatches", {
    method: "POST",
    headers: { "Authorization": "Bearer " + env.GH_DISPATCH_TOKEN, "Accept": "application/vnd.github+json",
               "User-Agent": "crinale-bot", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status === 204) {
    await env.SUBS.put("runs_seen", JSON.stringify({ ...seen, ...now }));
    await env.SUBS.put("runs_last_dispatch", String(Date.now()));
  }
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/tg" && req.method === "POST") {
      if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== (await secretOf(env))) return new Response("no", { status: 403 });
      const up = await req.json();
      try {
        if (up.message && up.message.text && up.message.reply_to_message && (await fbEdit(env, up.message))) {}
        else if (up.message && up.message.text) await onMessage(env, up.message);
        else if (up.callback_query) await onCallback(env, up.callback_query);
      } catch (e) { console.log("errore", e && e.stack); }
      return new Response("ok");
    }
    if (req.method === "OPTIONS") return new Response(null, { headers: cors(req) });
    if (url.pathname === "/event" && req.method === "POST") return submitEvent(req, env);
    if (url.pathname === "/events.json") return listEvents(req, env);
    if (url.pathname === "/report" && req.method === "POST") return submitReport(req, env);
    if (url.pathname === "/admin-note" && req.method === "POST") {
      // testo pronto per il canale WhatsApp, mandato in privato all'amministratore dalla pipeline
      if (req.headers.get("X-Secret") !== (await secretOf(env))) return new Response("no", { status: 403 });
      const admin = await env.SUBS.get("admin");
      if (!admin) return new Response("nessun amministratore: manda /admin al bot", { status: 409 });
      const { text } = await req.json();
      await tg(env, "sendMessage", { chat_id: admin, text: String(text || "").slice(0, 4000), link_preview_options: { is_disabled: true } });
      return new Response("ok");
    }
    if (url.pathname === "/fb-draft" && req.method === "POST") return fbDraft(req, env);
    if (url.pathname === "/reports.json") return listReports(req, env);
    if (url.pathname === "/setup") {
      // Collega il bot a questo worker. Ripeterlo non fa danni: reimposta sempre lo stesso indirizzo.
      const r = await tg(env, "setWebhook", { url: url.origin + "/tg", secret_token: await secretOf(env),
        allowed_updates: ["message", "callback_query"], drop_pending_updates: true });
      const cmds = {
        it: [["segui", "Scegli le località da seguire"], ["lista", "Le località che segui"], ["stop", "Cancellati"]],
        en: [["segui", "Pick places to follow"], ["lista", "Places you follow"], ["stop", "Unsubscribe"]],
      };
      await tg(env, "setMyCommands", { commands: cmds.en.map(([command, description]) => ({ command, description })) });
      await tg(env, "setMyCommands", { language_code: "it", commands: cmds.it.map(([command, description]) => ({ command, description })) });
      const me = await tg(env, "getMe", {});
      const n = (await env.SUBS.list({ prefix: "u:" })).keys.length;
      return Response.json({ webhook: r.ok, bot: me.result && me.result.username, iscritti: n });
    }
    return new Response("Crinale bot ⛰️");
  },
  async scheduled(event, env, ctx) {
    if (event.cron === "*/10 * * * *") ctx.waitUntil(checkRuns(env));
    else ctx.waitUntil(notifyAll(env));
  },
};
