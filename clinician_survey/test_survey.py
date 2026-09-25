import json, sys, threading, http.server, socketserver, os, functools

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8731
MEDIA = os.environ.get("SURVEY_SHOT_DIR", "/tmp/survey-shots")
os.makedirs(MEDIA, exist_ok=True)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

URL = f"http://127.0.0.1:{PORT}/index.html"
fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))
    if not cond:
        fails.append(name)

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)
    page.goto(URL)
    page.wait_for_selector("#surveyForm fieldset")

    check("storage mode is indexeddb over http", page.evaluate("Store.mode") == "indexeddb", page.evaluate("Store.mode"))
    check("section 6 locked initially", page.locator("#sec_s6 .lockmsg").count() == 1)
    check("q11 grid rendered", page.locator("#fs_q11 table.grid tbody tr").count() == 8)
    q11_head = page.evaluate("() => document.querySelector('#fs_q11 table.grid thead th').textContent")
    check("q11 row header names the decisions", q11_head == "Decision", q11_head)
    s7 = page.evaluate("""() => {
      const c = [...document.querySelectorAll('#sectionChips .chip')].find(n => n.textContent.includes('7. CLOSING'));
      return c ? c.className : '';
    }""")
    check("section 7 not marked complete with no required answers", s7 == "chip", s7)
    # Keyboard: a second Space must not move focus onto a different cell and overwrite the answer.
    na = page.locator("#fs_q11 table.grid tbody tr").first.locator("input").nth(2)
    na.focus()
    page.keyboard.press("Space")
    page.wait_for_timeout(80)
    page.keyboard.press("Space")
    page.wait_for_timeout(80)
    kept = page.evaluate("""() => {
      const a = document.activeElement;
      return {stored: draft.answers.q11.rows.medication_decisions, id: a.id, checked: !!a.checked};
    }""")
    check("q11 keyboard answer stays on the cell that was used",
          kept["stored"] == "na" and kept["checked"] and kept["id"] == "q11_medication_decisions_na", kept)
    check("q12b hidden initially", page.locator("#cond_q12b").is_hidden())

    # conditional: q12a selection reveals q12b
    page.locator("#fs_q12a input[type=checkbox]").first.check()
    page.wait_for_timeout(120)
    check("q12b revealed after q12a", page.locator("#cond_q12b").is_visible())

    # multi-select cap on q13
    for i in range(4):
        cb = page.locator("#fs_q13 .opt input[type=checkbox]").nth(i)
        if not cb.is_disabled():
            cb.check()
            page.wait_for_timeout(80)
    sel13 = page.evaluate("draft.answers.q13.selected.length")
    check("q13 capped at 3 selections", sel13 == 3, sel13)
    check("q13 cap message present", "3 of 3 selected" in page.locator("#fs_q13 .capmsg").inner_text())

    # fill everything else through the API the UI writes to, then re-render
    page.evaluate("""() => {
      const pick = (q) => q.options.filter(o=>!o.other)[0].code;
      const setMulti = (id, n=2) => { draft.answers[id] = { selected: (Q[id]||FOLLOWUPS[id]).options.filter(o=>!o.other).slice(0,n).map(o=>o.code), other:"" }; };
      const setSingle = (id, code) => { draft.answers[id] = { value: code || pick(Q[id]), other:"" }; };
      setMulti('q1'); setMulti('q2'); setSingle('q3');
      setMulti('q4'); draft.answers.q5={value:4}; draft.answers.q6={value:3}; setMulti('q7',3);
      setMulti('q8a'); setMulti('q8b'); setSingle('q9'); setMulti('q10',1);
      draft.answers.q11 = { rows: Object.fromEntries(Q.q11.rows.map((r,i)=>[r.code, i%3===0?'yes':(i%3===1?'no':'na')])) };
      setSingle('q14','yes'); setSingle('q15','no'); setSingle('q16','rarely');
      setMulti('q17',3);
      renderSurvey();
    }""")
    page.wait_for_timeout(200)
    check("q14b revealed for yes", page.locator("#cond_q14b").is_visible())
    check("q16b revealed for rarely", page.locator("#cond_q16b").is_visible())
    check("section 6 now unlocked", page.locator("#sec_s6 .lockmsg").count() == 0)
    check("section 6 preamble shown only after gate", "clinically useful partner" in page.locator("#sec_s6").inner_text())

    # q18 matrix + top3 cap
    page.evaluate("""() => {
      draft.answers.q18 = { rows: Object.fromEntries(Q.q18.rows.map((r,i)=>[r.code, ['high','medium','low','no_value'][i%4]])), top3: [] };
      renderSurvey();
    }""")
    later = page.locator("#fs_q18 table.grid tbody tr").nth(6).locator("input[type=checkbox]")
    later.focus()
    page.keyboard.press("Space")
    page.wait_for_timeout(80)
    top_focus = page.evaluate("""() => {
      const a = document.activeElement;
      return {top3: draft.answers.q18.top3, id: a.id, checked: !!a.checked};
    }""")
    check("q18 top-3 keyboard focus stays on the chosen row",
          top_focus["top3"] == ["documentation_tools"] and top_focus["checked"] and top_focus["id"] == "q18_top_documentation_tools",
          top_focus)
    page.evaluate("() => { draft.answers.q18.top3 = []; renderSurvey(); }")
    boxes = page.locator("#fs_q18 table.grid tbody tr td:last-child input")
    for i in range(4):
        b = boxes.nth(i)
        if not b.is_disabled():
            b.check()
            page.wait_for_timeout(80)
    top3 = page.evaluate("draft.answers.q18.top3.length")
    check("q18 top-3 capped at three", top3 == 3, top3)

    page.evaluate("""() => {
      draft.answers.q19={value:'partial_fit',other:''};
      draft.answers.q19b={selected:['specialist_interpretation','consultation_access'],other:''};
      draft.answers.q20={selected:['alert_fatigue','conflict_of_interest_overtesting'],other:''};
      draft.answers.q21={value:'all_through_treating_provider',other:''};
      draft.answers.q22={text:'Faster definitive turnaround.'};
      draft.answers.q23={text:'Nothing further.'};
      draft.collector='playwright-test';
      renderSurvey();
    }""")
    page.wait_for_timeout(150)
    prog = page.locator("#progLabel").inner_text()
    check("all required answered", "100%" in prog, prog)

    page.screenshot(path=f"{MEDIA}/survey-desktop.png", full_page=False)

    page.click("#btnSubmit")
    page.wait_for_timeout(500)
    stored = page.evaluate("Store.all().then(r=>r.length)")
    check("one submitted response stored", stored == 1, stored)
    rec = page.evaluate("Store.all().then(r=>r[0])")
    check("record marked complete", rec.get("complete") is True, rec.get("complete"))
    check("draft reset after submit", page.evaluate("requiredProgress().answered") == 0)

    # exports
    page.evaluate("loadDemo()")
    page.wait_for_timeout(700)
    page.evaluate("FILTERS.status='all'")
    total = page.evaluate("Store.all().then(r=>r.length)")
    check("demo data merged", total == 25, total)
    check("demo merge is idempotent", page.evaluate("mergeRecords(demoResponses(24)).then(r=>r.inserted)") == 0)

    wide = page.evaluate("Store.all().then(r=>wideCSV(r))")
    long_csv = page.evaluate("Store.all().then(r=>longCSV(r))")
    js = page.evaluate("Store.all().then(r=>exportJSON(r))")
    open("/tmp/svybuild/out_wide.csv", "w").write(wide)
    open("/tmp/svybuild/out_long.csv", "w").write(long_csv)
    open("/tmp/svybuild/out.json", "w").write(js)
    check("wide csv has 25 data rows", wide.count("\r\n") - 1 == 25, wide.count("\r\n") - 1)
    check("long csv non-trivial", long_csv.count("\r\n") > 500, long_csv.count("\r\n"))
    check("json parses with 25 responses", len(json.loads(js)["responses"]) == 25)

    # round trip: clear, re-import JSON, compare analytics
    before = page.evaluate("Store.all().then(r=>{ALL=r;FILTERS={role:[],setting:[],tenure:[],status:'all'};return JSON.stringify({k:kpis(filtered()),m:matrixSummary(filtered(),'q18'),q13:multiCounts(filtered(),'q13')});})")
    page.evaluate("Store.clearAll()")
    page.evaluate("txt => mergeRecords(JSON.parse(txt).responses)", js)
    page.wait_for_timeout(400)
    after = page.evaluate("Store.all().then(r=>{ALL=r;FILTERS={role:[],setting:[],tenure:[],status:'all'};return JSON.stringify({k:kpis(filtered()),m:matrixSummary(filtered(),'q18'),q13:multiCounts(filtered(),'q13')});})")
    check("JSON round trip preserves analytics", before == after)

    # round trip via wide CSV
    page.evaluate("Store.clearAll()")
    page.evaluate("txt => mergeRecords(recordsFromWideCSV(txt))", wide)
    page.wait_for_timeout(400)
    csv_after = page.evaluate("Store.all().then(r=>{ALL=r;FILTERS={role:[],setting:[],tenure:[],status:'all'};const f=filtered();return JSON.stringify({n:f.length,q18:matrixSummary(f,'q18').map(x=>[x.code,x.top3,x.weightedMean]),q13:multiCounts(f,'q13').items,q5:kpis(f).q5});})")
    ref = page.evaluate("txt => {const r=JSON.parse(txt).responses; return JSON.stringify({n:r.length,q18:matrixSummary(r,'q18').map(x=>[x.code,x.top3,x.weightedMean]),q13:multiCounts(r,'q13').items,q5:kpis(r).q5});}", js)
    check("wide CSV round trip preserves analytics", csv_after == ref, (csv_after[:200], ref[:200]))

    # statistics sanity against an independent computation
    vals = page.evaluate("Store.all().then(r=>r.map(x=>x.answers.q5&&x.answers.q5.value).filter(v=>typeof v==='number'))")
    import statistics
    exp_mean = statistics.mean(vals)
    exp_sd = statistics.stdev(vals)
    got = page.evaluate("Store.all().then(r=>({mean:Stats.mean(r.map(x=>x.answers.q5.value)),sd:Stats.sd(r.map(x=>x.answers.q5.value)),med:Stats.median(r.map(x=>x.answers.q5.value))}))")
    check("mean matches python", abs(got["mean"] - exp_mean) < 1e-9, (got["mean"], exp_mean))
    check("sample sd matches python", abs(got["sd"] - exp_sd) < 1e-9, (got["sd"], exp_sd))
    check("median matches python", abs(got["med"] - statistics.median(vals)) < 1e-9)

    # dashboard
    page.click("#tab-dash")
    page.wait_for_timeout(600)
    dash_text = page.locator("#dashRoot").inner_text()
    for needle in ["Overview", "Who responded", "Q18 \u2014 Value ranking", "Cross-tabulations", "Top barriers", "Free-text"]:
        check(f"dashboard section present: {needle}", needle in dash_text)
    check("four preset cross-tabs rendered", dash_text.count("\u00d7") >= 4, dash_text.count("\u00d7"))
    page.screenshot(path=f"{MEDIA}/dashboard-desktop.png", full_page=False)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
    page.wait_for_timeout(300)
    page.screenshot(path=f"{MEDIA}/dashboard-q18-ranking.png")

    # filters
    page.evaluate("FILTERS={role:['physician'],setting:[],tenure:[],status:'all'};renderDashboard()")
    page.wait_for_timeout(300)
    n_filtered = page.evaluate("filtered().length")
    n_all = page.evaluate("ALL.length")
    check("role filter reduces N", 0 < n_filtered <= n_all, (n_filtered, n_all))
    page.evaluate("FILTERS={role:[],setting:[],tenure:[],status:'all'};renderDashboard()")

    # report
    page.click("#tab-report")
    page.wait_for_timeout(500)
    rep_text = page.locator("#reportRoot").inner_text()
    check("report renders headline numbers", "Headline numbers" in rep_text)
    page.screenshot(path=f"{MEDIA}/report-desktop.png")

    # data tab
    page.click("#tab-data")
    page.wait_for_timeout(400)
    check("data tab lists stored responses", "Stored responses" in page.locator("#dataRoot").inner_text())

    # accessibility spot checks
    a11y = page.evaluate("""() => {
      const inputs=[...document.querySelectorAll('#surveyForm input,#surveyForm textarea')];
      const unlabelled=inputs.filter(i=>!i.closest('label') && !i.getAttribute('aria-label') && !document.querySelector('label[for="'+i.id+'"]'));
      return {inputs:inputs.length, unlabelled:unlabelled.length,
              legends:document.querySelectorAll('#surveyForm fieldset > legend').length,
              live:document.querySelectorAll('[aria-live]').length,
              tabs:document.querySelectorAll('[role=tab]').length};
    }""")
    page.click("#tab-survey")
    page.wait_for_timeout(200)
    a11y = page.evaluate("""() => {
      const inputs=[...document.querySelectorAll('#surveyForm input,#surveyForm textarea')];
      const unlabelled=inputs.filter(i=>!i.closest('label') && !i.getAttribute('aria-label') && !document.querySelector('label[for="'+i.id+'"]'));
      return {inputs:inputs.length, unlabelled:unlabelled.length,
              legends:document.querySelectorAll('#surveyForm fieldset > legend').length,
              live:document.querySelectorAll('[aria-live]').length};
    }""")
    check("every survey input is labelled", a11y["unlabelled"] == 0, a11y)
    check("each question is a fieldset with a legend", a11y["legends"] >= 20, a11y)

    # keyboard order, checked on a fresh page so focus starts at the document top
    kb = ctx.new_page()
    kb.goto(URL)
    kb.wait_for_selector("#surveyForm fieldset")
    order = []
    for _ in range(4):
        kb.keyboard.press("Tab")
        order.append(kb.evaluate("document.activeElement.className + '|' + document.activeElement.tagName"))
    check("skip link is first tab stop", order[0].startswith("skip"), order)
    check("tablist is reachable by keyboard", any("BUTTON" in o for o in order), order)
    kb.keyboard.press("Tab")
    kb.close()

    # mobile viewport
    mob = ctx.new_page()
    mob.set_viewport_size({"width": 390, "height": 844})
    mob.goto(URL)
    mob.wait_for_selector("#surveyForm fieldset")
    mob.evaluate("loadDemo()")
    mob.wait_for_timeout(600)
    grid_hidden = mob.evaluate("getComputedStyle(document.querySelector('#fs_q11 table.grid')).display")
    cards_shown = mob.evaluate("getComputedStyle(document.querySelector('#fs_q11 .gridcards')).display")
    check("grid falls back to cards on mobile", grid_hidden == "none" and cards_shown == "block", (grid_hidden, cards_shown))
    overflow = mob.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    check("no horizontal overflow on mobile", overflow, mob.evaluate("document.documentElement.scrollWidth"))
    mob.screenshot(path=f"{MEDIA}/survey-mobile.png")
    mob.click("#tab-dash")
    mob.wait_for_timeout(700)
    check("no horizontal overflow on mobile dashboard", mob.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), mob.evaluate("document.documentElement.scrollWidth"))
    mob.screenshot(path=f"{MEDIA}/dashboard-mobile.png")

    # interviewer mode survives a reload
    iv = ctx.new_page()
    iv.goto(URL)
    iv.wait_for_selector("#surveyForm fieldset")
    iv.locator("#interviewerMode").check()
    iv.evaluate("saveDraftNow()")
    iv.reload()
    iv.wait_for_selector("#surveyForm fieldset")
    iv.wait_for_timeout(300)
    guide = iv.locator("#interviewerPanel").inner_text() if iv.locator("#interviewerPanel").is_visible() else ""
    check("interviewer mode resumes with the guide",
          iv.locator("#interviewerMode").is_checked() and "Do not describe Progressive Diagnostics" in guide, guide[:80])
    iv.close()

    # file:// path exercises the localStorage fallback
    f = ctx.new_page()
    f.goto("file://" + ROOT + "/index.html")
    f.wait_for_selector("#surveyForm fieldset")
    f.wait_for_timeout(500)
    mode = f.evaluate("Store.mode")
    check("file:// opens and picks a working storage mode", mode in ("indexeddb", "localstorage"), mode)
    f.evaluate("loadDemo()")
    f.wait_for_timeout(600)
    check("file:// can store and read back", f.evaluate("Store.all().then(r=>r.length)") == 24, f.evaluate("Store.all().then(r=>r.length)"))

    check("no page errors", not errors, errors[:4])
    browser.close()

httpd.shutdown()
print("\n" + ("ALL CHECKS PASSED" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
