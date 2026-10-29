# /// script
# requires-python = ">=3.11, <3.14"
# dependencies = ["playwright==1.63.0"]
# ///
"""Offline gameplay checks in isolated background tabs of the existing Chrome."""
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()


def open_game(browser, width=1366, height=900, touch=False, storage=True):
    context = browser.contexts[0]
    browser_cdp = browser.new_browser_cdp_session()
    with context.expect_page() as created:
        browser_cdp.send("Target.createTarget", {
            "url": "about:blank", "background": True, "newWindow": False,
        })
    page = created.value
    browser_cdp.detach()
    page.set_viewport_size({"width": width, "height": height})
    cdp = context.new_cdp_session(page)
    cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
    cdp.send("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": touch,
    })
    cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": touch, "maxTouchPoints": 5 if touch else 1})
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1,
    })
    if storage:
        page.add_init_script("""(() => {
          const values=window.name ? JSON.parse(window.name) : {'bygga.best':'42'};
          Object.defineProperty(window,'localStorage',{value:{
            getItem:key=>values[key]??null,
            setItem:(key,value)=>{values[key]=String(value);window.name=JSON.stringify(values)},
            removeItem:key=>{delete values[key];window.name=JSON.stringify(values)}
          }});
        })()""")
    else:
        page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('Storage disabled')}})")
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda req: requests.append(req.url) if req.url.startswith("http") else None)
    page.goto(URL)
    page.wait_for_function("window.Bygga && Bygga.game")
    return page, cdp, errors, requests


def touch_event(cdp, kind, points):
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def point(x, y, ident=1):
    return {"x": x, "y": y, "id": ident, "radiusX": 5, "radiusY": 5}


def tap(page, cdp, selector):
    rect = page.locator(selector).bounding_box()
    touch_event(cdp, "touchStart", [point(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)])
    touch_event(cdp, "touchEnd", [])


def board_geometry(page):
    rect = page.locator("#board").bounding_box()
    scale = rect["width"] / 512
    return rect["x"] + 12 * scale, rect["y"] + 12 * scale, 61 * scale


def fixture(page, js=""):
    page.evaluate("""extra => {
      const g=Bygga.game;g.reset();
      g.tray=[{shape:'square-0',color:1},{shape:'line3-0',color:2},{shape:'tee-0',color:3}];
      if(extra) (new Function('g',extra))(g);
      Bygga.refresh();
    }""", js)


def check_layouts(browser):
    for width, height, touch in [
        (1440, 900, False), (1366, 768, False), (1024, 768, True),
        (768, 1024, True), (390, 844, True), (320, 568, True),
        (320, 480, True), (844, 390, True), (568, 320, True),
    ]:
        page, cdp, errors, requests = open_game(browser, width, height, touch)
        if (width, height) == (390, 844):
            page.screenshot(path="/tmp/bygga-title-phone.png")
        page.locator("#play").click()
        fixture(page, "for(const [i,c] of [[56,1],[57,1],[58,1],[59,2],[63,4],[55,4],[47,4],[48,1],[49,1],[50,1],[51,2],[43,2],[35,2],[60,5],[61,5],[53,5],[45,5],[46,4]])g.board[i]=c;")
        measures = page.evaluate("""() => {
          const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
          return {parts:['.hud','#board','.tray','.toolbar'].map(rect),
            scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,
            header:!!document.querySelector('header'),lang:document.documentElement.lang};
        }""")
        assert measures["scrollWidth"] <= width + 1, measures
        assert measures["scrollHeight"] <= height + 1, measures
        assert not measures["header"] and measures["lang"] == "sv"
        for r in measures["parts"]:
            assert r["x"] >= 0 and r["y"] >= 0 and r["right"] <= width + 1 and r["bottom"] <= height + 1, measures
        board = measures["parts"][1]
        assert abs(board["width"] - board["height"]) < 1
        for button in page.locator(".icon-button, .piece-slot").all():
            r = button.bounding_box()
            assert r["width"] >= 44 and r["height"] >= 44, r
        assert page.locator("#screen").is_hidden()
        page.screenshot(path=f"/tmp/bygga-{width}x{height}.png")
        assert not errors, errors
        assert not requests, requests
        page.close()
        print(f"PASS layout {width}×{height}, offline, Swedish, controls in bounds", flush=True)


def check_keyboard_saves(browser):
    page, _, errors, requests = open_game(browser)
    assert page.locator("#best").inner_text() == "42"
    page.locator("#play").click()
    fixture(page)
    page.keyboard.press("1")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("Bygga.cursor") == {"x": 1, "y": 1}
    page.keyboard.press("Enter")
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("Bygga.game.board[9]") == 1
    assert page.evaluate("Bygga.game.tray[0]") is None
    page.keyboard.press("2")
    page.keyboard.press("Escape")
    assert page.evaluate("Bygga.selected") == -1
    # A real keyboard placement triggers a crossing clear, scoring, sound, effects, and saving.
    fixture(page, "g.tray[0]={shape:'single-0',color:5};for(let i=1;i<8;i++){g.board[i]=2;g.board[i*8]=3}g.board[63]=4;")
    page.keyboard.press("1")
    page.keyboard.press("Space")
    page.wait_for_function("document.querySelector('#score').textContent==='401'")
    assert page.locator("#best").inner_text() == "401"
    assert page.evaluate("Bygga.game.totalLines") == 2
    assert page.evaluate("localStorage.getItem('bygga.best')") == "401"
    assert page.evaluate("JSON.parse(localStorage.getItem('bygga.save.v1')).score") == 401
    assert page.locator("#points").inner_text() == "+401"
    assert page.locator("#combo-text").inner_text() == "Kombo ×1"
    assert page.evaluate("Bygga.sound.context.state") == "running"
    page.locator("#sound").click()
    assert page.evaluate("localStorage.getItem('bygga.sound')") == "off"
    state = page.evaluate("Bygga.game.serialize()")
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.locator("#play").inner_text().strip() == "Fortsätt"
    assert page.evaluate("Bygga.game.serialize()") == state
    assert page.locator("#best").inner_text() == "401"
    assert page.locator("#sound").get_attribute("aria-pressed") == "false"
    page.locator("#play").click()
    page.locator("#help").click()
    assert page.locator("#help-dialog").is_visible()
    page.keyboard.press("1")
    assert page.evaluate("Bygga.selected") == -1
    page.keyboard.press("Escape")
    page.locator("#restart").click()
    assert page.locator("#restart-dialog").is_visible()
    page.locator("#cancel-restart").click()
    assert page.evaluate("Bygga.game.score") == 401
    page.locator("#restart").click()
    page.locator("#confirm-restart").click()
    assert page.evaluate("Bygga.game.score") == 0
    assert page.locator("#best").inner_text() == "401"
    # Native screen navigation at game-over and replay.
    fixture(page, "g.board=Array.from({length:64},(_,i)=>(Math.floor(i/8)+i%8)%2?1:0);g.tray=[{shape:'single-0',color:1},{shape:'square-0',color:2},{shape:'line2-0',color:3}]")
    page.keyboard.press("1"); page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('#screen').hidden")
    assert page.locator("#screen-title").inner_text() == "Slut på plats"
    assert page.evaluate("localStorage.getItem('bygga.save.v1')") is None
    page.locator("#screen-secondary").click()
    assert page.locator("#screen").is_hidden()
    page.locator("#restart").click()
    assert not page.evaluate("Bygga.game.over")
    assert page.evaluate("Bygga.game.moves") == 0
    assert not errors, errors
    assert not requests, requests
    page.close()
    print("PASS keyboard, cross clear, effects, sound unlock/mute, reload/resume, best, help, restart, end/replay", flush=True)


def check_touch(browser, width, height):
    page, cdp, errors, _ = open_game(browser, width, height, True, storage=False)
    tap(page, cdp, "#play")
    fixture(page)
    gx, gy, unit = board_geometry(page)
    rect = page.locator('[data-slot="0"]').bounding_box()
    origin = point(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    target = point(gx + 4 * unit, gy + 4 * unit + 24)
    touch_event(cdp, "touchStart", [origin])
    touch_event(cdp, "touchMove", [target])
    assert page.evaluate("Bygga.cursor") == {"x": 3, "y": 2}
    assert page.locator("#drag-piece").is_visible()
    if width == 390:
        page.screenshot(path="/tmp/bygga-touch-drag.png")
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("Bygga.game.board[19]") == 1
    assert page.locator("#drag-piece").is_hidden()
    # A second contact cannot acquire a different piece during an active drag.
    fixture(page)
    touch_event(cdp, "touchStart", [origin])
    touch_event(cdp, "touchMove", [target])
    other = point(gx + unit, gy + unit, 2)
    touch_event(cdp, "touchStart", [target, other])
    touch_event(cdp, "touchEnd", [other])
    assert page.evaluate("Bygga.game.moves") == 0
    touch_event(cdp, "touchCancel", [])
    assert page.evaluate("Bygga.game.moves") == 0
    assert page.locator("#drag-piece").is_hidden()
    # Tap-to-place fallback uses the selected shape's upper-left corner.
    tap(page, cdp, '[data-slot="1"]')
    touch_event(cdp, "touchStart", [point(gx + .5 * unit, gy + .5 * unit)])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("Bygga.game.board.slice(0,3)") == [2, 2, 2]
    # Invalid overlap and an off-board release leave the tray and score untouched.
    tap(page, cdp, '[data-slot="0"]')
    touch_event(cdp, "touchStart", [point(gx + .5 * unit, gy + .5 * unit)])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    touch_event(cdp, "touchStart", [origin])
    touch_event(cdp, "touchMove", [point(5, 5)])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("Bygga.game.tray[0].shape") == "square-0"
    # Losing focus cannot later drop a piece accidentally.
    touch_event(cdp, "touchStart", [origin])
    touch_event(cdp, "touchMove", [target])
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("String(window.getSelection())") == ""
    assert page.evaluate("window.scrollY") == 0
    assert not errors, errors
    page.close()
    print(f"PASS native touch drag/lift, tap-place, multi-contact cancel, invalid drop, blur, denied storage {width}×{height}", flush=True)


def check_audio(browser):
    page, _, errors, _ = open_game(browser)
    stats = page.evaluate("""async () => {
      const ctx=new OfflineAudioContext(2,44100*5,44100),s=new ByggaSound(ctx);
      s.play('start',1,0);s.play('pick',1,.6);s.play('place',1,.8);
      s.play('clear',2,1.2);s.play('allclear',5,2.1);s.play('over',1,3.4);
      const buffer=await ctx.startRendering(),a=buffer.getChannelData(0),b=buffer.getChannelData(1);
      let peak=0,power=0,stereo=0;for(let i=0;i<a.length;i++) {peak=Math.max(peak,Math.abs(a[i]),Math.abs(b[i]));power+=a[i]*a[i];stereo+=Math.abs(a[i]-b[i])}
      const mutedContext=new OfflineAudioContext(2,44100,44100),muted=new ByggaSound(mutedContext);
      muted.setEnabled(false);muted.play('clear',4,0);
      const silence=await mutedContext.startRendering();
      return {peak,rms:Math.sqrt(power/a.length),stereo,mutedPeak:Math.max(...silence.getChannelData(0))};
    }""")
    assert 0.03 < stats["peak"] < 0.98, stats
    assert stats["rms"] > 0.005 and stats["stereo"] > 1, stats
    assert stats["mutedPeak"] == 0, stats
    assert not errors, errors
    page.close()
    print(f"PASS rendered stereo effects, no clipping, mute silence: {stats}", flush=True)


def check_mouse(browser):
    page, _, errors, _ = open_game(browser)
    page.locator("#play").click()
    fixture(page, "g.tray[0]={shape:'single-0',color:5};for(let i=1;i<8;i++){g.board[i]=2;g.board[i*8]=3}g.board[63]=4;")
    gx, gy, unit = board_geometry(page)
    r = page.locator('[data-slot="0"]').bounding_box()
    page.mouse.move(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
    page.mouse.down()
    page.mouse.move(gx + unit / 2, gy + unit / 2, steps=12)
    assert page.evaluate("Bygga.cursor") == {"x": 0, "y": 0}
    assert page.evaluate("Bygga.game.preview(Bygga.selected,0,0).count") == 2
    page.screenshot(path="/tmp/bygga-clear-preview.png")
    page.mouse.up()
    assert page.evaluate("Bygga.game.score") == 401
    page.wait_for_timeout(130)
    # Decoration must not block the following move.
    page.keyboard.press("2")
    assert page.evaluate("Bygga.selected") == 1
    page.keyboard.press("Enter")
    assert page.evaluate("Bygga.game.moves") == 2
    page.emulate_media(reduced_motion="reduce")
    fixture(page, "g.tray[0]={shape:'single-0',color:1};for(let i=1;i<8;i++)g.board[i]=1;")
    page.keyboard.press("1"); page.keyboard.press("Enter")
    assert page.locator("#score").inner_text() == "401"
    assert page.evaluate("Bygga.game.board.every(v=>v===0)")
    assert not errors, errors
    page.close()
    print("PASS mouse drag, full crossing preview, input during particles, reduced-motion all-clear", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--effects-only", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not args.effects_only:
            check_layouts(browser)
            check_keyboard_saves(browser)
            check_touch(browser, 390, 844)
            check_touch(browser, 1024, 768)
            check_touch(browser, 844, 390)
        check_mouse(browser)
        check_audio(browser)
