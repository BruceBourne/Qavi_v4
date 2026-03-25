import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import (get_advisor_clients, get_meetings_for_advisor, get_meetings_for_client,
                      create_meeting, update_meeting_status, get_pending_requests_for_advisor,
                      approve_meeting_request, reject_meeting_request,
                      create_meeting_request, get_all_advisors, get_client_advisors)
from utils.crypto import fmt_date, title_case
from datetime import date, timedelta

WORK_TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]
ALL_TIMES  = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)]

def _is_weekday(d):
    return d.weekday() < 5

def _gcal_link(title, d, t, dur_mins=60):
    end_h  = int(t[:2]) + dur_mins // 60
    end_m  = int(t[3:]) + dur_mins % 60
    if end_m >= 60: end_h += 1; end_m -= 60
    ds = d.replace("-","")
    return (f"https://calendar.google.com/calendar/render?action=TEMPLATE"
            f"&text={title.replace(' ','+')}+%7C+Qavi"
            f"&dates={ds}T{t.replace(':','')}00/{ds}T{end_h:02d}{end_m:02d}00"
            f"&details=Qavi+Portfolio+Meeting")

def _status_badge(status):
    colors = {"scheduled":"#4F7EFF","completed":"#2ECC7A","cancelled":"#FF5A5A"}
    return f'<span style="color:{colors.get(status,"#8892AA")};font-weight:600;font-size:.8rem">{status.capitalize()}</span>'

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    back_button(fallback="dashboard", key="top")
    user = st.session_state.user
    role = user["role"]

    st.markdown('<div class="page-title">Meetings</div>', unsafe_allow_html=True)

    # ── ADVISOR ────────────────────────────────────────────────────────────
    if role in ("advisor","owner"):
        meetings  = get_meetings_for_advisor(user["id"])
        requests  = get_pending_requests_for_advisor(user["id"])
        clients   = get_advisor_clients(user["id"])

        tab1, tab2, tab3 = st.tabs([
            f"  📋 Meetings ({len(meetings)})  ",
            f"  🔔 Requests ({len(requests)})  ",
            "  ➕ Schedule  ",
        ])

        with tab1:
            filt = st.selectbox("Filter", ["all","scheduled","completed","cancelled"],
                                format_func=lambda x: "All" if x=="all" else x.capitalize())
            shown = [m for m in meetings if filt=="all" or m["status"]==filt]
            if not shown: st.info("No meetings found.")
            for m in shown:
                client_name = m.get("client_name") or m.get("advisor_client_id","—")
                with st.expander(f"📅  {fmt_date(m['meeting_date'])}  {m['meeting_time']}  ·  {title_case(str(client_name))}  ·  {m.get('title','Meeting')}"):
                    c1,c2 = st.columns(2)
                    c1.markdown(f"**Date:** {fmt_date(m['meeting_date'])}<br>**Time:** {m['meeting_time']}<br>**Duration:** {m['duration_mins']} min<br>**Requested by:** {m.get('requested_by','advisor').capitalize()}", unsafe_allow_html=True)
                    meet_link_html = f'<a href="{m["meet_link"]}" target="_blank" style="color:#4F7EFF">Join Meeting →</a>' if m.get("meet_link") else "—"
                    c2.markdown(f"**Status:** {_status_badge(m['status'])}<br>**Notes:** {m.get('notes','—') or '—'}<br>**Meet Link:** {meet_link_html}", unsafe_allow_html=True)

                    b1,b2,b3 = st.columns(3)
                    if m["status"] == "scheduled":
                        if b1.button("✅ Complete", key=f"comp_{m['id']}", use_container_width=True):
                            update_meeting_status(m["id"], "completed"); st.rerun()
                        if b2.button("❌ Cancel",   key=f"canc_{m['id']}", use_container_width=True):
                            update_meeting_status(m["id"], "cancelled"); st.rerun()
                    gcal = _gcal_link(m.get("title","Meeting"), m["meeting_date"], m["meeting_time"], m["duration_mins"])
                    b3.markdown(f'<a href="{gcal}" target="_blank" style="display:block;text-align:center;background:#161B27;color:#F0F4FF;padding:.42rem .9rem;border-radius:8px;border:1px solid #252D40;font-size:.82rem;text-decoration:none">📅 Google Calendar</a>', unsafe_allow_html=True)

        with tab2:
            if not requests:
                st.info("No pending meeting requests from clients.")
            for req in requests:
                with st.expander(f"🔔  {title_case(req['client_name'])}  ·  Preferred: {fmt_date(req['preferred_date'])} {req['preferred_time']}"):
                    st.markdown(f"**Message:** {req.get('message','—')}")
                    if st.session_state.get(f"approve_{req['id']}"):
                        with st.form(f"apf_{req['id']}"):
                            t  = st.text_input("Title", value="Portfolio Review")
                            c1,c2 = st.columns(2)
                            d  = c1.date_input("Date", value=date.fromisoformat(req["preferred_date"]))
                            tm = c2.selectbox("Time", ALL_TIMES,
                                              index=ALL_TIMES.index(req["preferred_time"]) if req["preferred_time"] in ALL_TIMES else 0)
                            dur = st.selectbox("Duration (min)", [30,45,60,90,120], index=2)
                            ml  = st.text_input("Meet Link (optional)", placeholder="https://meet.google.com/…")
                            n   = st.text_area("Notes", height=60)
                            if st.form_submit_button("Confirm Meeting", use_container_width=True):
                                approve_meeting_request(req["id"], user["id"], req["client_user_id"],
                                                        t, str(d), tm, dur, ml, n)
                                st.session_state.pop(f"approve_{req['id']}", None)
                                st.success("Meeting scheduled!"); st.rerun()
                        if st.button("Cancel", key=f"ca_{req['id']}"): st.session_state.pop(f"approve_{req['id']}", None); st.rerun()
                    else:
                        b1,b2 = st.columns(2)
                        if b1.button("✅ Approve & Schedule", key=f"ap_{req['id']}", use_container_width=True):
                            st.session_state[f"approve_{req['id']}"] = True; st.rerun()
                        if b2.button("❌ Decline",            key=f"rj_{req['id']}", use_container_width=True):
                            reject_meeting_request(req["id"]); st.rerun()

        with tab3:
            if not clients:
                st.info("No clients to schedule with."); return
            st.caption("As an advisor you can schedule meetings at any time. Add a Meet link so clients can join.")
            with st.form("sched_form"):
                cl_sel = st.selectbox("Client", [c["id"] for c in clients],
                                      format_func=lambda x: title_case(next(c["client_name"] for c in clients if c["id"]==x)))
                title  = st.text_input("Title", value="Portfolio Review")
                c1,c2  = st.columns(2)
                mdate  = c1.date_input("Date", value=date.today()+timedelta(days=1))
                mtime  = c2.selectbox("Time", ALL_TIMES, index=ALL_TIMES.index("10:00") if "10:00" in ALL_TIMES else 0)
                dur    = st.selectbox("Duration (min)", [30,45,60,90,120], index=2)
                ml     = st.text_input("Meet Link (optional)", placeholder="https://meet.google.com/…")
                notes  = st.text_area("Notes", height=60)
                if st.form_submit_button("Schedule Meeting", use_container_width=True):
                    cl_obj = next(c for c in clients if c["id"]==cl_sel)
                    client_uid = cl_obj.get("client_id")
                    create_meeting(user["id"], cl_sel, client_uid, title, str(mdate), mtime, dur, ml, notes, "advisor")
                    gcal = _gcal_link(title, str(mdate), mtime, dur)
                    st.success(f"Meeting scheduled for {fmt_date(str(mdate))} at {mtime}.")
                    st.markdown(f'<a href="{gcal}" target="_blank" style="color:#4F7EFF">📅 Add to Google Calendar →</a>', unsafe_allow_html=True)

    # ── CLIENT ─────────────────────────────────────────────────────────────
    else:
        meetings = get_meetings_for_client(user["id"])
        tab1, tab2 = st.tabs([f"  📋 My Meetings ({len(meetings)})  ", "  📅 Request a Meeting  "])

        with tab1:
            upcoming = [m for m in meetings if m["meeting_date"] >= str(date.today()) and m["status"]=="scheduled"]
            past     = [m for m in meetings if m["meeting_date"] <  str(date.today()) or  m["status"]!="scheduled"]
            if upcoming:
                st.markdown("#### Upcoming")
                for m in upcoming:
                    with st.expander(f"📅  {fmt_date(m['meeting_date'])} {m['meeting_time']}  ·  {m.get('title','Meeting')}", expanded=True):
                        c1,c2 = st.columns(2)
                        c1.markdown(f"**Date:** {fmt_date(m['meeting_date'])}<br>**Time:** {m['meeting_time']}<br>**Duration:** {m['duration_mins']} min", unsafe_allow_html=True)
                        meet_html = f'<a href="{m["meet_link"]}" target="_blank" style="color:#4F7EFF">Join →</a>' if m.get("meet_link") else "—"
                        c2.markdown(f"**Meet Link:** {meet_html}<br>**Notes:** {m.get('notes','—') or '—'}", unsafe_allow_html=True)
                        gcal = _gcal_link(m.get("title","Meeting"), m["meeting_date"], m["meeting_time"], m["duration_mins"])
                        st.markdown(f'<a href="{gcal}" target="_blank" style="color:#4F7EFF;font-size:.83rem">📅 Add to Google Calendar →</a>', unsafe_allow_html=True)
            if past:
                st.markdown(""); st.markdown("#### Past")
                for m in past[:10]:
                    sc = {"completed":"#2ECC7A","cancelled":"#FF5A5A","scheduled":"#4F7EFF"}.get(m["status"],"#8892AA")
                    st.markdown(f'<div style="display:flex;justify-content:space-between;padding:.55rem .9rem;background:#161B27;border-radius:8px;margin-bottom:.3rem;border:1px solid #252D40"><span style="font-size:.84rem">{fmt_date(m["meeting_date"])} {m["meeting_time"]} · {m.get("title","Meeting")}</span><span style="color:{sc};font-size:.8rem;font-weight:600">{m["status"].capitalize()}</span></div>', unsafe_allow_html=True)
            if not meetings:
                st.info("No meetings yet. Request one from the next tab.")

        with tab2:
            advisors     = get_client_advisors(user["id"])
            all_advisors = get_all_advisors()
            st.markdown("#### Request a Meeting")
            st.caption("You can request a meeting with any registered advisor — Mon–Fri, 9:00 AM to 6:00 PM only. Your advisor will confirm the time.")

            advisor_opts = {}
            for a in advisors:
                advisor_opts[a["advisor_id"]] = f"{title_case(a.get('advisor_name',''))} (your advisor)"
            for a in all_advisors:
                if a["id"] not in advisor_opts:
                    advisor_opts[a["id"]] = title_case(a.get("full_name","") or a["username"])

            if not advisor_opts:
                st.info("No advisors registered yet."); return

            with st.form("request_form"):
                adv_sel = st.selectbox("Advisor", list(advisor_opts.keys()),
                                       format_func=lambda x: advisor_opts[x])
                next_day = date.today() + timedelta(days=1)
                while not _is_weekday(next_day): next_day += timedelta(days=1)
                pref_date = st.date_input("Preferred Date (Mon–Fri only)", value=next_day,
                                           min_value=date.today()+timedelta(days=1))
                pref_time = st.selectbox("Preferred Time (IST)", WORK_TIMES)
                message   = st.text_area("Message (optional)", placeholder="e.g. Would like to review my portfolio allocation.")
                if st.form_submit_button("Send Request", use_container_width=True):
                    if not _is_weekday(pref_date):
                        st.error("Please choose a weekday (Monday–Friday).")
                    else:
                        create_meeting_request(adv_sel, user["id"], str(pref_date), pref_time, message)
                        st.success("Request sent! Your advisor will confirm shortly.")
    back_button(fallback="dashboard", label="← Back", key="bot")
