import { useEffect, useState, FormEvent, ReactNode } from "react";
import { api, setToken, hasToken } from "./api";

const TYPES: Record<string, [string, string, string]> = {
  ANNOUNCEMENT: ["📢", "Announcement", "bg-white"], SCHEDULE_UPDATE: ["🔔", "Schedule update", "bg-amber-50"],
  VENUE_CHANGE: ["📍", "Venue change", "bg-amber-50"], REMINDER: ["⏰", "Reminder", "bg-white"], POLL: ["📊", "Poll", "bg-mint"],
  FEEDBACK_REQUEST: ["⭐", "Feedback request", "bg-mint"], EMERGENCY_ALERT: ["🚨", "Emergency alert", "bg-red-50"],
  EVENT_INFO: ["ℹ️", "Event information", "bg-white"], SPONSOR_UPDATE: ["🤝", "Sponsor update", "bg-white"], GENERAL: ["💬", "General update", "bg-white"] };
const ago = (s: string) => { const m = Math.round((Date.now() - new Date(s + "Z").getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

function useLoad<T>(fn: () => Promise<T>, deps: any[], every = 0): [T | null, () => void, string] {
  const [d, setD] = useState<T | null>(null); const [e, setE] = useState("");
  const load = () => fn().then(x => { setD(x); setE(""); }).catch(x => setE(x.message));
  useEffect(() => { setD(null); load(); if (!every) return; const i = setInterval(load, every); return () => clearInterval(i); }, deps);
  return [d, load, e];
}
const Err = ({ t }: { t: string }) => t ? <p role="alert" className="rounded-md bg-red-100 p-3 text-sm text-red-900">{t}</p> : null;
const Empty = ({ children }: { children: ReactNode }) => <p className="rounded-lg border border-dashed border-ink/30 p-6 text-center text-ink/70">{children}</p>;
const Bar = ({ pct, label, right }: { pct: number; label: string; right: string }) => (
  <div className="mb-2"><div className="flex justify-between text-sm"><span>{label}</span><span>{right}</span></div>
    <div className="h-2.5 rounded bg-ink/10"><div className="h-2.5 rounded bg-forest" style={{ width: `${pct}%` }} /></div></div>);

function Feed({ eid }: { eid: number }) {
  const [items, , err] = useLoad<any[]>(() => api(`/events/${eid}/feed`), [eid], 10000);
  if (err) return <Err t={err} />; if (!items) return <p>Loading feed…</p>;
  if (!items.length) return <Empty>No updates yet. Publish the first one from the Publish tab.</Empty>;
  return <ol className="space-y-3">{items.map(i => { const [ic, name, bg] = TYPES[i.type] || TYPES.GENERAL;
    return <li key={i.id} className={`${bg} rounded-2xl border-l-8 p-4 ${i.priority === "URGENT" ? "border-coral" : i.priority === "IMPORTANT" ? "border-signal" : "border-forest/30"}`}>
      <div className="flex justify-between text-sm text-ink/70"><span>{ic} {name}{i.priority !== "NORMAL" && ` (${i.priority.toLowerCase()})`}</span><span>{ago(i.created_at)}</span></div>
      <h3 className="font-display text-lg font-bold">{i.title}</h3><p>{i.content}</p>
      <p className="mt-2 flex gap-2 text-xs">{i.channels.split(",").map((c: string) => <span key={c} className="rounded bg-ink/10 px-2 py-0.5">{c === "SMS" ? "SMS sent" : c === "USSD" ? "USSD updated" : c === "VOICE" ? "Voice call" : "On feed"}</span>)}</p></li>; })}</ol>;
}

function Publish({ eid }: { eid: number }) {
  const [msg, setMsg] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); setBusy(true); setErr(""); setMsg("");
    try { const r = await api(`/events/${eid}/announcements`, { title: f.get("title"), content: f.get("content"), type: f.get("type"), priority: f.get("priority"),
        channels: ["FEED", ...["SMS", "USSD"].filter(c => f.get(c))] });
      setMsg(r.sms?.error || `Published.${r.sms ? (r.sms.simulated ? ` ${r.sms.queued} SMS simulated (demo mode, nothing was sent).` : ` ${r.sms.queued} SMS queued with Africa's Talking.`) : ""}`);
      (e.target as HTMLFormElement).reset(); } catch (x: any) { setErr(x.message); } setBusy(false); };
  return <form onSubmit={submit} className="max-w-xl space-y-3"><Err t={err} />{msg && <p role="status" className="rounded-md bg-mint p-3 text-sm">{msg}</p>}
    <div><label className="lbl" htmlFor="title">Title</label><input id="title" name="title" required minLength={2} className="field" /></div>
    <div><label className="lbl" htmlFor="content">Message</label><textarea id="content" name="content" required minLength={2} rows={3} className="field" /></div>
    <div className="grid grid-cols-2 gap-3"><div><label className="lbl" htmlFor="type">Type</label><select id="type" name="type" className="field">{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v[1]}</option>)}</select></div>
      <div><label className="lbl" htmlFor="priority">Priority</label><select id="priority" name="priority" className="field"><option>NORMAL</option><option>IMPORTANT</option><option>URGENT</option></select></div></div>
    <fieldset className="flex gap-5 text-sm"><legend className="lbl">Send through</legend><label><input type="checkbox" checked disabled /> Activity feed</label>
      <label><input type="checkbox" name="SMS" /> SMS</label><label><input type="checkbox" name="USSD" defaultChecked /> USSD</label></fieldset>
    <button className="btn-signal" disabled={busy}>{busy ? "Publishing…" : "Publish update"}</button></form>;
}

function Schedule({ eid, editable }: { eid: number; editable?: boolean }) {
  const [rows, reload, err] = useLoad<any[]>(() => api(`/events/${eid}/schedule`), [eid], editable ? 0 : 10000); const [e2, setE2] = useState("");
  const move = async (id: number, f: FormData) => { try { await api(`/schedule/${id}`, { venue: f.get("venue"), notify_sms: !!f.get("sms") }, "PATCH"); setE2(""); reload(); } catch (x: any) { setE2(x.message); } };
  if (!rows) return <Err t={err} />; if (!rows.length) return <Empty>No sessions yet.</Empty>;
  return <div className="space-y-2"><Err t={err || e2} />{rows.map(s => <form key={s.id} onSubmit={e => { e.preventDefault(); move(s.id, new FormData(e.currentTarget)); }}
    className="flex flex-wrap items-center gap-3 rounded-xl bg-white p-3"><b className="w-14 font-display">{s.start_time}</b><span className="flex-1">{s.title}</span>
    {editable ? <><input name="venue" defaultValue={s.venue} aria-label={`Venue for ${s.title}`} className="field w-36" /><label className="text-sm"><input type="checkbox" name="sms" /> SMS</label><button className="btn">Move session</button></> : <span className="rounded bg-mint px-2 py-1 text-sm">{s.venue}</span>}</form>)}</div>;
}

function Polls({ eid, phone, admin }: { eid: number; phone?: string; admin?: boolean }) {
  const [polls, reload, err] = useLoad<any[]>(() => api(`/events/${eid}/polls`), [eid], 10000); const [e2, setE2] = useState("");
  const act = (fn: () => Promise<any>) => fn().then(() => { setE2(""); reload(); }).catch(x => setE2(x.message));
  const create = (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget);
    act(() => api(`/events/${eid}/polls`, { question: f.get("q"), options: String(f.get("o")).split("\n").map(s => s.trim()).filter(Boolean) })); (e.target as HTMLFormElement).reset(); };
  return <div className="max-w-xl space-y-4"><Err t={err || e2} />
    {admin && <form onSubmit={create} className="space-y-2 rounded-xl bg-white p-4"><label className="lbl" htmlFor="q">Question</label><input id="q" name="q" required className="field" />
      <label className="lbl" htmlFor="o">Options (one per line, 2 to 6)</label><textarea id="o" name="o" required rows={4} className="field" /><button className="btn">Create poll</button></form>}
    {polls && !polls.length && <Empty>No polls yet.</Empty>}
    {polls?.map(p => <section key={p.id} className="rounded-xl bg-white p-4"><h3 className="mb-2 font-display font-bold">{p.question} {p.status === "CLOSED" && <em className="text-sm font-normal">(closed)</em>}</h3>
      {p.options.map((o: any) => <div key={o.id}><Bar pct={o.percent} label={o.text} right={`${o.percent}% (${o.votes})`} />
        {phone && p.status === "OPEN" && <button className="btn mb-2 py-1 text-sm" onClick={() => act(() => api(`/polls/${p.id}/vote`, { option_id: o.id, phone }))}>Vote {o.text}</button>}</div>)}
      <p className="text-sm text-ink/70">{p.responses} responses</p>
      {admin && p.status === "OPEN" && <button className="btn mt-2 py-1 text-sm" onClick={() => act(() => api(`/polls/${p.id}/close`, {}, "POST"))}>Close poll</button>}</section>)}</div>;
}

function Issues({ eid }: { eid: number }) {
  const [rows, reload, err] = useLoad<any[]>(() => api(`/events/${eid}/issues`), [eid], 15000);
  if (!rows) return <Err t={err} />; if (!rows.length) return <Empty>No issues reported. Attendees can report them by USSD or web.</Empty>;
  return <table className="w-full rounded-xl bg-white text-left"><thead><tr className="border-b text-sm"><th className="p-3">Issue</th><th>Category</th><th>Description</th><th>Status</th></tr></thead>
    <tbody>{rows.map(i => <tr key={i.id} className="border-b last:border-0"><td className="p-3">#{i.id}</td><td>{i.category}</td><td>{i.description}</td>
      <td><select aria-label={`Status of issue ${i.id}`} value={i.status} className="field w-36" onChange={e => api(`/issues/${i.id}`, { status: e.target.value }, "PATCH").then(reload)}>
        <option value="OPEN">Open</option><option value="IN_PROGRESS">In progress</option><option value="RESOLVED">Resolved</option></select></td></tr>)}</tbody></table>;
}

function Analytics({ eid }: { eid: number }) {
  const [a, , err] = useLoad<any>(() => api(`/events/${eid}/analytics`), [eid], 15000);
  const [n] = useLoad<any[]>(() => api(`/events/${eid}/notifications`), [eid], 15000);
  const [fb] = useLoad<any[]>(() => api(`/events/${eid}/feedback/summary`), [eid], 15000);
  if (!a) return <Err t={err} />; const ch = a.engagement_by_channel; const tot = ch.WEB + ch.USSD || 1;
  const stats = [["Registered", a.registered], ["Checked in", `${a.checked_in} (${a.attendance_rate}%)`], ["SMS delivered", a.sms.DELIVERED], ["SMS failed", a.sms.FAILED],
    ["USSD interactions", a.ussd_interactions], ["Feedback", a.feedback_responses], ["Poll votes", a.poll_responses], ["Issues", a.issues_reported]];
  return <div className="space-y-6"><p className="text-sm">{a.demo_mode ? "Demo mode: SMS, voice and airtime are simulated. Every number here is counted from the database." : "Live mode."}</p>
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">{stats.map(([k, v]) => <div key={k as string} className="rounded-xl bg-white p-4"><dd className="font-display text-3xl font-extrabold">{v}</dd><dt className="text-sm">{k}</dt></div>)}</dl>
    <section className="max-w-lg rounded-xl bg-white p-4"><h3 className="mb-2 font-display font-bold">Engagement by channel</h3>
      <Bar pct={100 * ch.WEB / tot} label="Web" right={ch.WEB} /><Bar pct={100 * ch.USSD / tot} label="USSD" right={ch.USSD} /></section>
    <section className="rounded-xl bg-white p-4"><h3 className="mb-2 font-display font-bold">Notifications</h3>{!n?.length ? <Empty>No notifications yet.</Empty> :
      <table className="w-full text-left text-sm"><thead><tr><th>Message</th><th>Recipients</th><th>Sent</th><th>Delivered</th><th>Failed</th></tr></thead>
        <tbody>{n.map((x, i) => <tr key={i} className="border-t"><td className="py-2 pr-2">{x.message.slice(0, 60)}{x.simulated && <b className="ml-2 rounded bg-signal px-1.5 text-xs">simulated</b>}</td><td>{x.recipients}</td><td>{x.SENT}</td><td>{x.DELIVERED}</td><td>{x.FAILED}</td></tr>)}</tbody></table>}</section>
    <section className="max-w-lg rounded-xl bg-white p-4"><h3 className="mb-2 font-display font-bold">Session feedback</h3>{fb?.map(s => <Bar key={s.session_id} pct={(s.average || 0) * 20} label={s.title} right={s.average ? `${s.average}/5 (${s.responses})` : "no ratings"} />)}</section></div>;
}

function Events({ done }: { done: (id: number) => void }) {
  const [res, setRes] = useState<any>(null); const [err, setErr] = useState("");
  const submit = async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); setErr("");
    try { const r = await api("/events", Object.fromEntries(new FormData(e.currentTarget))); setRes(r); done(r.id); } catch (x: any) { setErr(x.message); } };
  const F = ({ n, l, t = "text", req = true }: any) => <div><label className="lbl" htmlFor={n}>{l}</label><input id={n} name={n} type={t} required={req} className="field" /></div>;
  return <div className="max-w-xl space-y-3">{res && <p role="status" className="rounded-md bg-mint p-3 text-sm">Event created. USSD code: <b>{res.ussd_code}</b>. Attendees can register on the Explore demo page or by USSD.</p>}<Err t={err} />
    <form onSubmit={submit} className="space-y-3 rounded-xl bg-white p-4"><F n="name" l="Event name" /><div><label className="lbl" htmlFor="description">Description</label><textarea id="description" name="description" rows={2} className="field" /></div>
      <div className="grid grid-cols-3 gap-3"><F n="date" l="Date" t="date" /><F n="start_time" l="Start time" t="time" /><F n="end_time" l="End time" t="time" /></div>
      <F n="venue" l="Venue" /><F n="location" l="Location" req={false} /><button className="btn-signal">Create event</button></form></div>;
}

function Attendees({ eid }: { eid: number }) {
  const [rows, reload, err] = useLoad<any[]>(() => api(`/events/${eid}/attendees`), [eid], 15000);
  const [sel, setSel] = useState<number[]>([]); const [msg, setMsg] = useState(""); const [e2, setE2] = useState("");
  const run = (fn: () => Promise<string>) => fn().then(m => { setMsg(m); setE2(""); reload(); }).catch(x => { setE2(x.message); setMsg(""); });
  const voice = (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const t = String(new FormData(e.currentTarget).get("m"));
    run(async () => { const r = await api(`/events/${eid}/voice`, { message: t, attendee_ids: sel }); return `Voice alert sent to ${r.recipients} attendee(s)${r.simulated ? " (simulated, no calls made)" : ""}.`; }); };
  if (!rows) return <Err t={err} />; if (!rows.length) return <Empty>No attendees yet.</Empty>;
  return <div className="space-y-4"><Err t={err || e2} />{msg && <p role="status" className="rounded-md bg-mint p-3 text-sm">{msg}</p>}
    <table className="w-full rounded-xl bg-white text-left text-sm"><thead><tr className="border-b"><th className="p-3">Call</th><th>Name</th><th>Phone</th><th>Joined by</th><th>Actions</th></tr></thead>
      <tbody>{rows.map(a => <tr key={a.id} className="border-b last:border-0"><td className="p-3"><input type="checkbox" aria-label={`Select ${a.name} for voice alert`} checked={sel.includes(a.id)} disabled={!sel.includes(a.id) && sel.length >= 10}
        onChange={() => setSel(sel.includes(a.id) ? sel.filter(x => x !== a.id) : [...sel, a.id])} /></td>
        <td>{a.name}{a.is_demo && <b className="ml-2 rounded bg-signal px-1.5 text-xs">demo</b>}</td><td>{a.phone}</td><td>{a.registration_source}</td>
        <td className="space-x-2 py-2">{a.checked_in ? <span>Checked in</span> : <button className="btn py-1" onClick={() => run(async () => { await api(`/events/${eid}/checkin`, { phone: a.phone }); return `${a.name} checked in.`; })}>Check in</button>}
          <button className="btn py-1" onClick={() => run(async () => { const r = await api(`/events/${eid}/rewards`, { attendee_id: a.id, amount: 20 }); return `Reward for ${r.participant}: ${r.amount}, ${r.status.toLowerCase()}${r.simulated ? " (simulated, no airtime sent)" : ""}.`; })}>Reward KES 20</button></td></tr>)}</tbody></table>
    <form onSubmit={voice} className="max-w-xl space-y-2 rounded-xl bg-white p-4"><label className="lbl" htmlFor="m">Urgent voice message (tick up to 10 people above)</label>
      <textarea id="m" name="m" required minLength={2} rows={2} className="field" /><button className="btn" disabled={!sel.length}>Send voice alert to {sel.length} selected</button></form></div>;
}

const CATS = ["Venue", "Technical Problem", "Security", "Accessibility", "Lost Item", "Medical Assistance", "Other"];
function Engage({ eid, phone }: { eid: number; phone: string }) {
  const [ss] = useLoad<any[]>(() => api(`/events/${eid}/schedule`), [eid]); const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const send = (path: string, body: any) => api(path, body).then(() => { setMsg("Thank you. Your response was sent."); setErr(""); }).catch(x => { setErr(x.message); setMsg(""); });
  return <div className="grid gap-4 md:grid-cols-2"><div className="md:col-span-2"><Err t={err} />{msg && <p role="status" className="rounded-md bg-mint p-3 text-sm">{msg}</p>}</div>
    <form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); send(`/events/${eid}/feedback`, { session_id: Number(f.get("s")), phone, rating: Number(f.get("r")) }); }} className="space-y-2 rounded-xl bg-white p-4">
      <h3 className="font-display font-bold">Rate a session</h3><label className="lbl" htmlFor="s">Session</label><select id="s" name="s" className="field">{ss?.map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select>
      <label className="lbl" htmlFor="r">Rating</label><select id="r" name="r" className="field">{[5, 4, 3, 2, 1].map(n => <option key={n} value={n}>{n} of 5</option>)}</select><button className="btn">Send rating</button></form>
    <form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); send(`/events/${eid}/issues`, { phone, category: f.get("c"), description: f.get("d") }); (e.target as HTMLFormElement).reset(); }} className="space-y-2 rounded-xl bg-white p-4">
      <h3 className="font-display font-bold">Report a problem</h3><label className="lbl" htmlFor="c">Category</label><select id="c" name="c" className="field">{CATS.map(x => <option key={x}>{x}</option>)}</select>
      <label className="lbl" htmlFor="d">What happened?</label><textarea id="d" name="d" rows={2} className="field" /><button className="btn">Report issue</button></form></div>;
}

const TABS = ["Activity feed", "Publish", "Schedule", "Polls", "Attendees", "Issues", "Analytics", "New event"];
function Dashboard({ out }: { out: () => void }) {
  const [tab, setTab] = useState(0); const [events, reloadEv, err] = useLoad<any[]>(() => api("/events"), []); const [eid, setEid] = useState(0);
  const cur = events?.find(e => e.id === (eid || events[0]?.id));
  if (!events) return <div className="p-6"><Err t={err} /></div>;
  if (!cur) return <div className="p-6"><h1 className="mb-4 font-display text-2xl font-extrabold">Create your first event</h1><Events done={id => { reloadEv(); setEid(id); }} /></div>;
  return <div className="min-h-screen md:flex"><nav className="bg-forest p-4 text-white md:w-56"><h1 className="mb-4 font-display text-xl font-extrabold">Activity Feed</h1>
    <ul className="flex gap-1 overflow-x-auto md:block">{TABS.map((t, i) => <li key={t}><button onClick={() => setTab(i)} aria-current={tab === i} className={`w-full whitespace-nowrap rounded-md px-3 py-2 text-left ${tab === i ? "bg-signal font-bold text-ink" : "hover:bg-white/10"}`}>{t}</button></li>)}</ul>
    <button onClick={out} className="mt-4 text-sm underline">Log out</button></nav>
    <main className="flex-1 p-4 md:p-8"><header className="mb-6 flex flex-wrap items-center gap-3"><select aria-label="Event" className="field w-auto font-display font-bold" value={cur.id} onChange={e => setEid(+e.target.value)}>{events.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
      <span className="rounded-full bg-forest px-3 py-1 text-sm font-bold text-white"><span className="pulse-dot mr-1 text-signal">●</span>{cur.status}</span></header>
      <h2 className="mb-4 font-display text-2xl font-extrabold">{TABS[tab]}</h2>
      {[<Feed eid={cur.id} />, <Publish eid={cur.id} />, <Schedule eid={cur.id} editable />, <Polls eid={cur.id} admin />, <Attendees eid={cur.id} />, <Issues eid={cur.id} />, <Analytics eid={cur.id} />, <Events done={id => { reloadEv(); setEid(id); }} />][tab]}</main></div>;
}

function Join({ back }: { back: () => void }) {
  const [events] = useLoad<any[]>(() => api("/events"), []); const [me, setMe] = useState<any>(null); const [err, setErr] = useState("");
  const ev = events?.[0];
  const reg = async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); setErr("");
    try { setMe(await api(`/events/${ev.id}/attendees`, { name: f.get("name"), phone: f.get("phone"), organization: f.get("org") || "" })); } catch (x: any) { setErr(x.message); } };
  return <main className="mx-auto max-w-2xl p-4"><button onClick={back} className="mb-4 underline">Back</button>
    {!ev ? <Empty>No event is open for registration yet.</Empty> : !me ? <form onSubmit={reg} className="space-y-3 rounded-2xl bg-white p-6"><h1 className="font-display text-2xl font-extrabold">Register for {ev.name}</h1>
      <p>{ev.date} at {ev.venue}. You will get a confirmation SMS. No smartphone? Dial the event USSD code instead.</p><Err t={err} />
      <div><label className="lbl" htmlFor="n">Full name</label><input id="n" name="name" required minLength={2} className="field" /></div>
      <div><label className="lbl" htmlFor="p">Phone number</label><input id="p" name="phone" required inputMode="tel" placeholder="0712 345 678" className="field" /></div>
      <div><label className="lbl" htmlFor="o">Organization (optional)</label><input id="o" name="org" className="field" /></div><button className="btn-signal">Register</button></form> :
      <div className="space-y-6"><header className="rounded-2xl bg-forest p-5 text-white"><p className="text-sm"><span className="pulse-dot text-signal">●</span> Live</p><h1 className="font-display text-2xl font-extrabold">{ev.name}</h1><p>Registered as {me.name}. Updates appear here automatically.</p></header>
        <section><h2 className="mb-2 font-display text-xl font-bold">Latest updates</h2><Feed eid={ev.id} /></section>
        <section><h2 className="mb-2 font-display text-xl font-bold">Schedule</h2><Schedule eid={ev.id} /></section>
        <section><h2 className="mb-2 font-display text-xl font-bold">Polls</h2><Polls eid={ev.id} phone={me.phone} /></section>
        <section><h2 className="mb-2 font-display text-xl font-bold">Feedback and issues</h2><Engage eid={ev.id} phone={me.phone} /></section></div>}</main>;
}

function Login({ back, done }: { back: () => void; done: () => void }) {
  const [reg, setReg] = useState(false); const [err, setErr] = useState("");
  const go = async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); setErr("");
    try { if (reg) await api("/auth/register", { name: f.get("name"), email: f.get("email"), password: f.get("password") });
      const r = await api("/auth/login", { email: f.get("email"), password: f.get("password") }); setToken(r.access_token); done(); } catch (x: any) { setErr(x.message === "Please check the form and try again." && reg ? "Use a password with at least 8 characters." : x.message); } };
  return <main className="mx-auto max-w-sm p-4"><button onClick={back} className="mb-4 underline">Back</button><form onSubmit={go} className="space-y-3 rounded-2xl bg-white p-6">
    <h1 className="font-display text-2xl font-extrabold">{reg ? "Create organizer account" : "Organizer log in"}</h1><Err t={err} />
    {reg && <div><label className="lbl" htmlFor="nm">Name</label><input id="nm" name="name" required className="field" /></div>}
    <div><label className="lbl" htmlFor="em">Email</label><input id="em" name="email" type="email" required defaultValue={reg ? "" : "demo@activityfeed.africa"} className="field" /></div>
    <div><label className="lbl" htmlFor="pw">Password</label><input id="pw" name="password" type="password" required className="field" /></div>
    <button className="btn-signal w-full">{reg ? "Create account" : "Log in"}</button>
    <button type="button" className="text-sm underline" onClick={() => setReg(!reg)}>{reg ? "I already have an account" : "Create an organizer account"}</button>
    {!reg && <p className="text-xs text-ink/70">Demo password is printed in the server log on first start.</p>}</form></main>;
}

const FEATURES = [["Real-time updates", "Publish once. The feed, SMS and USSD all show the same change."], ["Reach every phone", "Feature phones join and follow the event by USSD and SMS. No internet needed."],
  ["Live engagement", "Polls, session ratings and issue reports, from a smartphone or a basic phone."], ["Smart event analytics", "See registrations, SMS delivery and USSD use as they happen."]];
function Landing({ go }: { go: (v: string) => void }) {
  return <div><header className="bg-forest px-6 py-16 text-white md:py-24"><div className="mx-auto max-w-4xl">
    <h1 className="font-display text-4xl font-extrabold leading-tight md:text-6xl">Every event has a story. Keep everyone in the loop.</h1>
    <p className="mt-5 max-w-2xl text-lg">Activity Feed connects organizers and attendees through real-time updates, SMS, USSD, feedback and engagement, even when attendees don't have internet access.</p>
    <div className="mt-8 flex flex-wrap gap-3"><button className="btn-signal" onClick={() => go("login")}>Create an event</button>
      <button className="rounded-lg border-2 border-white px-5 py-2.5 font-bold" onClick={() => go("join")}>Explore demo</button></div></div></header>
    <main className="mx-auto max-w-4xl space-y-12 px-6 py-12"><ul className="grid gap-4 md:grid-cols-2">{FEATURES.map(([t, d]) => <li key={t} className="border-l-4 border-signal bg-white p-5"><h2 className="font-display text-xl font-bold">{t}</h2><p>{d}</p></li>)}</ul>
      <section className="grid gap-6 md:grid-cols-2"><div><h2 className="font-display text-2xl font-extrabold">Internet-independent event communication</h2>
        <p className="mt-2">A smartphone with internet uses the web app. A feature phone with only a mobile network uses USSD and SMS. Both take part in the same event.</p></div>
        <div><h2 className="font-display text-2xl font-extrabold">Built on Africa's Talking</h2><p className="mt-2">USSD for menus and registration, SMS with delivery tracking, Voice for urgent alerts, and Airtime for rewards.</p></div></section></main></div>;
}

export default function App() {
  const [v, setV] = useState(hasToken() ? "app" : "landing");
  if (v === "app") return <Dashboard out={() => { setToken(""); setV("landing"); }} />;
  if (v === "login") return <Login back={() => setV("landing")} done={() => setV("app")} />;
  if (v === "join") return <Join back={() => setV("landing")} />;
  return <Landing go={setV} />;
}
