# /// script
# requires-python = ">=3.11, <3.14"
# dependencies = ["playwright==1.63.0"]
# ///
"""Offline gameplay checks in isolated background tabs of the existing Chrome."""
from pathlib import Path
import time
from playwright.sync_api import sync_playwright, Error as PlaywrightError

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()
TEST_PAGES = []
SCREENSHOTS = True
BACKGROUND_RENDER = False


def capture_screenshot(page, path):
    if SCREENSHOTS:
        page.screenshot(path=path)


def open_game(browser, width=1366, height=900, touch=False, storage=True, url=URL, offline=True, background_render=False):
    context = browser.contexts[0]
    browser_cdp = browser.new_browser_cdp_session()
    target = browser_cdp.send("Target.createTarget", {
        "url": "about:blank", "background": True, "newWindow": False,
    })["targetId"]
    # Another suite or the user may open a tab at the same time. Match our
    # exact target before changing viewport, storage or network settings.
    page, cdp = None, None
    deadline = time.monotonic() + 5
    while page is None and time.monotonic() < deadline:
        for candidate in context.pages:
            session = None
            try:
                session = context.new_cdp_session(candidate)
                if session.send("Target.getTargetInfo")["targetInfo"]["targetId"] == target:
                    page, cdp = candidate, session
                    break
                session.detach()
            except PlaywrightError:
                if session:
                    try:
                        session.detach()
                    except PlaywrightError:
                        pass
        if page is None:
            browser_cdp.send("Target.getTargetInfo", {"targetId": target})
            time.sleep(.01)
    if page is None:
        browser_cdp.send("Target.closeTarget", {"targetId": target})
        browser_cdp.detach()
        raise AssertionError(f"Could not attach to test tab {target}")
    TEST_PAGES.append(page)
    browser_cdp.detach()
    page.set_viewport_size({"width": width, "height": height})
    cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
    cdp.send("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": touch,
    })
    cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": touch, "maxTouchPoints": 5 if touch else 1})
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": offline, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1,
    })
    if storage is True:
        page.add_init_script("""(() => {
          const values=window.name ? JSON.parse(window.name) : {'bygga.rules2.best':'42'};
          Object.defineProperty(window,'localStorage',{value:{
            getItem:key=>values[key]??null,
            setItem:(key,value)=>{values[key]=String(value);window.name=JSON.stringify(values)},
            removeItem:key=>{delete values[key];window.name=JSON.stringify(values)}
          }});
        })()""")
    elif storage is False:
        page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('Storage disabled')}})")
    if background_render or BACKGROUND_RENDER:
        # A covered desktop window can suspend compositor-driven RAF even
        # with focus emulation. Only the test tab's drawing clock uses timers;
        # game state continues to change exclusively through normal input.
        page.add_init_script("""(() => {
          window.__nativeFrames={request:requestAnimationFrame,cancel:cancelAnimationFrame};
          window.requestAnimationFrame=fn=>setTimeout(()=>fn(performance.now()),16);
          window.cancelAnimationFrame=id=>clearTimeout(id);
        })()""")
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda req: requests.append(req.url) if req.url.startswith("http") else None)
    page.goto(url)
    page.wait_for_function("window.Bygga && Bygga.game")
    return page, cdp, errors, requests


def touch_event(cdp, kind, points, timestamp=None):
    params = {"type": kind, "touchPoints": points}
    if timestamp is not None:
        params["timestamp"] = timestamp
    cdp.send("Input.dispatchTouchEvent", params)


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


def select_with_keyboard(page, slot):
    # Focus/resize cancellation may legitimately clear a preview between input
    # events. Verify it before reading coordinates, and retry only selection.
    for _ in range(3):
        page.keyboard.press(str(slot + 1))
        selection = page.evaluate("({slot:Bygga.selected,cursor:Bygga.cursor})")
        if selection["slot"] == slot and selection["cursor"] is not None:
            return selection["cursor"]
        page.wait_for_timeout(60)
    raise AssertionError({"wanted_slot": slot, "selection": selection,
                          "state": page.evaluate("({over:Bygga.game.over,screen:!document.querySelector('#screen').hidden,dialogs:[...document.querySelectorAll('dialog[open]')].map(d=>d.id)})")})


def check_layouts(browser):
    for width, height, touch in [
        (1440, 900, False), (1366, 768, False), (1024, 768, True),
        (768, 1024, True), (390, 844, True), (320, 568, True),
        (320, 480, True), (844, 390, True), (568, 320, True),
    ]:
        page, cdp, errors, requests = open_game(browser, width, height, touch)
        if (width, height) == (390, 844):
            capture_screenshot(page, "/tmp/bygga-title-phone.png")
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
        capture_screenshot(page, f"/tmp/bygga-{width}x{height}.png")
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
    assert page.evaluate("localStorage.getItem(`bygga.rules${ByggaEngine.RULES_VERSION}.best`)") == "401"
    assert page.evaluate("JSON.parse(localStorage.getItem(`bygga.rules${ByggaEngine.RULES_VERSION}.save`)).score") == 401
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
    assert page.evaluate("localStorage.getItem(`bygga.rules${ByggaEngine.RULES_VERSION}.save`)") is None
    page.locator("#screen-secondary").click()
    assert page.locator("#screen").is_hidden()
    page.locator("#restart").click()
    assert not page.evaluate("Bygga.game.over")
    assert page.evaluate("Bygga.game.moves") == 0
    assert not errors, errors
    assert not requests, requests
    page.close()
    print("PASS keyboard, cross clear, effects, sound unlock/mute, reload/resume, best, help, restart, end/replay", flush=True)


def check_rules_storage(browser):
    page, _, errors, requests = open_game(browser)
    page.evaluate("""() => {
      const version=ByggaEngine.RULES_VERSION;
      const old={...Bygga.game.serialize(),score:70000,moves:400};
      localStorage.removeItem(`bygga.rules${version}.best`);
      for(const prefix of ['bygga',`bygga.rules${version-1}`]) {
        localStorage.setItem(`${prefix}.best`,'70000');
        localStorage.setItem(prefix==='bygga'?'bygga.save.v1':`${prefix}.save`,JSON.stringify(old));
      }
      localStorage.setItem('bygga.sound','off');
    }""")
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.locator("#best").inner_text() == "0"
    assert page.locator("#play").inner_text().strip() == "Spela"
    assert page.evaluate("Bygga.game.score") == 0
    assert page.locator("#sound").get_attribute("aria-pressed") == "false"
    # A still-open old release must not import its record through storage events.
    page.evaluate("""() => {
      for(const key of ['bygga.best',`bygga.rules${ByggaEngine.RULES_VERSION-1}.best`])
        window.dispatchEvent(new StorageEvent('storage',{key,newValue:'80000'}));
    }""")
    assert page.locator("#best").inner_text() == "0"
    page.locator("#play").click()
    fixture(page, "g.tray[0]={shape:'single-0',color:1}")
    page.keyboard.press("1"); page.keyboard.press("Enter")
    saved = page.evaluate("Bygga.game.serialize()")
    assert saved["score"] == 1
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.evaluate("Bygga.game.serialize()") == saved
    assert page.locator("#best").inner_text() == "1"
    assert page.locator("#play").inner_text().strip() == "Fortsätt"
    assert page.evaluate("localStorage.getItem('bygga.best')") == "70000"
    page.evaluate("window.dispatchEvent(new StorageEvent('storage',{key:`bygga.rules${ByggaEngine.RULES_VERSION}.best`,newValue:'50'}))")
    assert page.locator("#best").inner_text() == "50"
    assert not errors, errors
    assert not requests, requests
    page.close()
    print("PASS scoring-version reset, old saved run excluded, stale-tab record ignored, current save/record resume, sound preserved", flush=True)


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
        capture_screenshot(page, "/tmp/bygga-touch-drag.png")
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
    assert page.evaluate("[0,8,16].map(i=>Bygga.game.board[i])") == [2, 2, 2]
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


def check_stones(browser):
    page, cdp, errors, requests = open_game(browser, 390, 844, True)
    tap(page, cdp, "#play")
    fixture(page, "g.score=4999;g.random=()=>.999;g.tray[0]={shape:'single-0',color:5};g.tray[1]={shape:'line3-1',color:2};")
    gx, gy, unit = board_geometry(page)
    tap(page, cdp, '[data-slot="0"]')
    touch_event(cdp, "touchStart", [point(gx + .5 * unit, gy + .5 * unit)])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.score") == 5000
    assert page.evaluate("Bygga.game.board[63]===ByggaEngine.STONE")
    assert page.locator("#toast strong").inner_text() == "En ruta blev sten"
    assert "sten" in page.locator("#board").get_attribute("aria-label")
    state = page.evaluate("Bygga.game.serialize()")
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.evaluate("Bygga.game.serialize()") == state
    tap(page, cdp, "#play")
    # A native tap cannot place a three-cell line across the stone at (7,7).
    tap(page, cdp, '[data-slot="1"]')
    state = page.evaluate("Bygga.game.serialize()")
    touch_event(cdp, "touchStart", [point(gx + 5.5 * unit, gy + 7.5 * unit)])
    assert page.evaluate("Bygga.game.preview(1,5,7)") is None
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.serialize()") == state
    fixture(page, "g.score=5000;g.board[0]=ByggaEngine.STONE;for(let i=1;i<7;i++)g.board[i]=2;g.tray[0]={shape:'single-0',color:5};")
    tap(page, cdp, '[data-slot="0"]')
    touch_event(cdp, "touchStart", [point(gx + 7.5 * unit, gy + .5 * unit)])
    assert page.evaluate("Bygga.game.preview(0,7,0).count") == 0
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.board.slice(0,8)") == [-1, 2, 2, 2, 2, 2, 2, 5]
    assert page.evaluate("Bygga.game.totalLines") == 0
    page.wait_for_timeout(850)
    pixel = page.evaluate("""() => {
      const c=document.querySelector('#board'),s=c.width/512;
      return [...c.getContext('2d').getImageData((12+.3*61)*s,(12+.55*61)*s,1,1).data];
    }""")
    assert pixel[3] == 255 and 70 < pixel[0] < 180 and abs(pixel[0] - pixel[2]) < 45, pixel
    capture_screenshot(page, "/tmp/bygga-stones-phone.png")
    assert not errors, errors
    assert not requests, requests
    page.close()
    print("PASS milestone stone, native-touch collision, blocked clear preview, rendering, save/resume offline", flush=True)


def check_limited_help(browser):
    page, cdp, errors, requests = open_game(browser, 390, 844, True)
    tap(page, cdp, "#play")
    fixture(page, """
      g.board=Array.from({length:64},(_,i)=>{
        const x=i%8,y=Math.floor(i/8);
        return y===0||y===7?0:(x+y)%3===0?ByggaEngine.STONE:1;
      });
      const rolls=[0,0,.95,0,.25,0,.999,.999];
      g.tray=ByggaEngine.deal(g.board,()=>rolls.shift());
    """)
    assert page.evaluate("Bygga.game.tray.map(p=>ByggaEngine.hasMove(Bygga.game.board,[p]))") == [True, False, False]
    gx, gy, unit = board_geometry(page)
    tap(page, cdp, '[data-slot="0"]')
    touch_event(cdp, "touchStart", [point(gx + .5 * unit, gy + .5 * unit)])
    touch_event(cdp, "touchEnd", [])
    page.wait_for_function("!document.querySelector('#screen').hidden")
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("Bygga.game.over")
    assert page.locator("#screen-title").inner_text() == "Slut på plats"
    tap(page, cdp, "#play")
    fixture(page, """
      g.score=4999;g.random=()=>0;g.board[0]=3;
      g.tray=[{shape:'single-0',color:5},null,null];
    """)
    tap(page, cdp, '[data-slot="0"]')
    touch_event(cdp, "touchStart", [point(gx + 1.5 * unit, gy + .5 * unit)])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.board.slice(0,3)") == [3, 5, -1]
    assert page.evaluate("Bygga.game.tray.every(Boolean)&&ByggaEngine.hasMove(Bygga.game.board,Bygga.game.tray)")
    assert not errors, errors
    assert not requests, requests
    page.close()
    print("PASS native-touch two-row trap ends, stones use empty squares, refill offers an opening after stone placement", flush=True)


def check_single_tap_rotation(browser, width, height, touch):
    page, cdp, errors, requests = open_game(browser, width, height, touch)
    page.locator("#play").click()
    rect = page.locator('[data-slot="0"]').bounding_box()
    origin = point(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    gx, gy, unit = board_geometry(page)

    def down(p):
        if touch:
            touch_event(cdp, "touchStart", [p])
        else:
            page.mouse.move(p["x"], p["y"])
            page.mouse.down()

    def move(p):
        if touch:
            touch_event(cdp, "touchMove", [p])
        else:
            page.mouse.move(p["x"], p["y"])

    def up():
        if touch:
            touch_event(cdp, "touchEnd", [])
        else:
            page.mouse.up()

    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    # Each stationary press turns exactly once, on release; four restore it.
    for rotation in range(4):
        down(origin)
        assert page.evaluate("Bygga.game.tray[0].rotation||0") == rotation
        move(point(origin["x"] + 3, origin["y"] + 2))
        up()
        assert page.evaluate("Bygga.game.tray[0].rotation||0") == (rotation + 1) % 4
        assert page.evaluate("Bygga.game.moves") == 0
        assert page.evaluate("Bygga.selected") == 0
        assert page.locator("#drag-piece").is_hidden()
    # Blur/cancel and an out-and-back drag cannot accidentally count as taps.
    before = page.evaluate("Bygga.game.serialize()")
    down(origin)
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    up()
    assert page.evaluate("Bygga.game.serialize()") == before
    if touch:
        down(origin)
        touch_event(cdp, "touchCancel", [])
        assert page.evaluate("Bygga.game.serialize()") == before
    down(origin)
    move(point(origin["x"] + 25, origin["y"]))
    move(origin)
    up()
    assert page.evaluate("Bygga.game.serialize()") == before
    # Direct drags preserve orientation; a prior tap intentionally turns it.
    for rotated in (False, True):
        fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
        if rotated:
            down(origin); up()
        w, h = (1, 3) if rotated else (3, 1)
        down(origin)
        move(point(gx + (2 + w / 2) * unit,
                   gy + (1 + h if touch else 1 + h / 2) * unit + (24 if touch else 0)))
        assert page.evaluate("Bygga.game.tray[0].rotation||0") == int(rotated)
        assert page.evaluate("Bygga.cursor") == {"x": 2, "y": 1}
        up()
        cells = [10, 18, 26] if rotated else [10, 11, 12]
        assert page.evaluate("cells=>cells.map(i=>Bygga.game.board[i])", cells) == [4, 4, 4]
        assert page.evaluate("Bygga.game.moves") == 1
    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    down(origin); up()
    saved = page.evaluate("Bygga.game.serialize()")
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.evaluate("Bygga.game.serialize()") == saved
    assert page.locator("#best").inner_text() == "42"
    page.locator("#play").click()
    # A tray tap selects as well as rotates; the following board tap only places.
    down(origin); up()
    down(point(gx + 2.5 * unit, gy + 1.5 * unit)); up()
    assert page.evaluate("[10,11,12].map(i=>Bygga.game.board[i])") == [4, 4, 4]
    if not touch:
        fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
        page.keyboard.press("1")
        assert page.evaluate("Bygga.game.tray[0].rotation||0") == 0
        page.locator('[data-slot="0"]').focus()
        page.keyboard.press("Space")
        assert page.evaluate("Bygga.game.tray[0].rotation") == 1
        assert page.evaluate("Bygga.game.moves") == 0
    assert not errors, errors
    assert not requests, requests
    page.close()
    print(f"PASS single {'tap' if touch else 'click'} rotation, jitter, cancel, drag safety, tap-place, save/record {width}×{height}", flush=True)


def check_rotation_mouse_keyboard(browser):
    page, _, errors, _ = open_game(browser)
    page.locator("#play").click()
    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    page.locator('[data-slot="0"]').click(button="right")
    assert page.evaluate("Bygga.game.tray[0].rotation") == 1
    assert page.evaluate("Bygga.game.moves") == 0
    state = page.evaluate("Bygga.game.serialize()")
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.evaluate("Bygga.game.serialize()") == state
    page.locator("#play").click()
    page.keyboard.press("1"); page.keyboard.press("r")
    assert page.evaluate("Bygga.game.tray[0].rotation") == 2
    page.keyboard.press("Shift+R")
    assert page.evaluate("Bygga.game.tray[0].rotation") == 1
    gx, gy, unit = board_geometry(page)
    page.mouse.move(gx + unit, gy + unit)
    page.keyboard.press("1")
    aimed = page.evaluate("Bygga.cursor")
    page.mouse.move(5, 5)
    assert page.evaluate("Bygga.cursor") == aimed, "Mouse leaving must not erase a keyboard preview"
    # Exercise the autoplay recovery path with a genuine game cancellation.
    page.evaluate("document.addEventListener('keydown',()=>queueMicrotask(()=>window.dispatchEvent(new Event('blur'))),{once:true})")
    assert select_with_keyboard(page, 0) == {"x": 0, "y": 0}
    page.keyboard.press("Enter")
    assert page.evaluate("[0,8,16].map(i=>Bygga.game.board[i])") == [4, 4, 4]
    assert page.evaluate("Bygga.game.score") == 3
    fixture(page, "g.board.fill(ByggaEngine.STONE);for(let y=1;y<=3;y++)g.board[y*8+3]=0;g.tray=[{shape:'line3-0',color:2},null,null];")
    assert "unavailable" not in page.locator('[data-slot="0"]').get_attribute("class")
    page.locator('[data-slot="0"]').click(button="right")
    page.keyboard.press("1")
    assert page.evaluate("Bygga.cursor") == {"x": 3, "y": 1}
    page.keyboard.press("Enter")
    assert page.evaluate("Bygga.game.over")
    assert not errors, errors
    page.close()
    print("PASS right-click, R/Shift+R, rotated placement/save/resume, rotation-only fit stays playable", flush=True)


def check_rotation_tap(browser, width, height):
    page, cdp, errors, requests = open_game(browser, width, height, True)
    tap(page, cdp, "#play")
    contacts, timestamp = set(), 0

    def send(kind, points, elapsed=.04):
        nonlocal contacts, timestamp
        # Covered-window CDP acknowledgements may each take a second. Supply
        # native event timestamps so a short tap stays short despite transport.
        timestamp = time.time() if kind == "touchStart" and not contacts else timestamp + elapsed
        touch_event(cdp, kind, points, timestamp)
        ids = {p["id"] for p in points}
        if kind in ("touchStart", "touchMove"):
            contacts = ids
        elif kind == "touchCancel" or not points:
            contacts.clear()
        else:
            contacts -= ids
    r = page.locator('[data-slot="0"]').bounding_box()
    first = point(r["x"] + r["width"] / 2 - 18, r["y"] + r["height"] / 2)
    second = point(first["x"] + 36, first["y"], 2)
    # Both simultaneous contacts and slightly staggered taps work. Either
    # finger can lift first; a pair must rotate only once and never place.
    for order in ("together", "first", "second"):
        fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
        if order == "together":
            send("touchStart", [first, second])
        else:
            send("touchStart", [first])
            send("touchStart", [first, second])
        if order != "together":
            send("touchEnd", [first if order == "first" else second])
        send("touchEnd", [])
        assert page.evaluate("Bygga.game.tray[0].rotation") == 1, order
        assert page.evaluate("Bygga.game.moves") == 0
        assert page.evaluate("Bygga.game.score") == 0
        assert page.evaluate("Bygga.selected") == 0
        assert page.evaluate("Bygga.game.board.every(v=>v===0)")
        assert page.locator("#drag-piece").is_hidden()
    saved = page.evaluate("Bygga.game.serialize()")
    page.reload()
    page.wait_for_function("window.Bygga")
    assert page.evaluate("Bygga.game.serialize()") == saved
    tap(page, cdp, "#play")
    # Small tap jitter is fine; a hold, pan, cancellation or third finger
    # must not be interpreted as a tap.
    for gesture in ("jitter", "hold", "pan", "cancel", "third"):
        fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
        send("touchStart", [first, second])
        if gesture in ("pan", "jitter"):
            distance = 22 if gesture == "pan" else 4
            moved = [point(first["x"] + distance, first["y"] + 2),
                     point(second["x"] + distance, second["y"] + 2, 2)]
            send("touchMove", moved)
            page.wait_for_timeout(40)
            send("touchMove", [first, second])
        elif gesture == "third":
            send("touchStart", [first, second, point(first["x"], first["y"] - 35, 3)])
        send("touchCancel" if gesture == "cancel" else "touchEnd", [], elapsed=.48 if gesture == "hold" else .04)
        assert page.evaluate("Bygga.game.tray[0].rotation||0") == (1 if gesture == "jitter" else 0), gesture
        assert page.evaluate("Bygga.game.moves") == 0, gesture
    # A second-finger tap during an existing drag must not silently turn it.
    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    gx, gy, unit = board_geometry(page)
    held = point(gx + 3.5 * unit, gy + 3 * unit + 24)
    added = point(held["x"] + 36, held["y"], 2)
    send("touchStart", [first])
    send("touchMove", [held])
    send("touchStart", [held, added])
    send("touchEnd", [added])
    assert page.evaluate("Bygga.game.tray[0].rotation||0") == 0
    target = point(gx + 4.5 * unit, gy + 3 * unit + 24)
    send("touchMove", [target])
    page.wait_for_function("Bygga.cursor?.x===3 && Bygga.cursor?.y===2")
    send("touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("[19,20,21].map(i=>Bygga.game.board[i])") == [4, 4, 4]
    assert not errors, errors
    assert not requests, requests
    page.close()
    print(f"PASS native two-finger tap, both release orders, jitter, cancellation, drag safety, save/resume {width}×{height}", flush=True)


def check_rotation_touch(browser, width, height):
    page, cdp, errors, _ = open_game(browser, width, height, True)
    tap(page, cdp, "#play")
    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    r = page.locator('[data-slot="0"]').bounding_box()
    first = point(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
    second = point(first["x"] + 65, first["y"], 2)
    turned = point(first["x"], first["y"] - 65, 2)
    touch_event(cdp, "touchStart", [first])
    touch_event(cdp, "touchStart", [first, second])
    touch_event(cdp, "touchMove", [first, turned])
    page.wait_for_function("Bygga.game.tray[0].rotation===3")
    assert page.evaluate("Bygga.game.tray[0].rotation") == 3
    touch_event(cdp, "touchEnd", [first])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 0
    assert page.evaluate("Bygga.selected") == 0
    assert page.evaluate("Bygga.game.tray[0].rotation") == 3, "Twist release must not add a tap rotation"
    # Rotate during a lifted drag, remove the second finger, then continue
    # dragging and release the first finger to place the new orientation.
    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    gx, gy, unit = board_geometry(page)
    origin = first
    first = point(gx + 3.5 * unit, gy + 3 * unit + 24)
    second = point(first["x"] + 65, first["y"], 2)
    turned = point(first["x"], first["y"] + 65, 2)
    touch_event(cdp, "touchStart", [origin])
    touch_event(cdp, "touchMove", [first])
    touch_event(cdp, "touchStart", [first, second])
    touch_event(cdp, "touchMove", [first, turned])
    page.wait_for_function("Bygga.game.tray[0].rotation===1")
    assert page.evaluate("Bygga.game.tray[0].rotation") == 1
    # CDP touchEnd lists the contacts to lift, not the contacts that remain.
    touch_event(cdp, "touchEnd", [turned])
    target = point(gx + 4.5 * unit, gy + 4 * unit + 24)
    touch_event(cdp, "touchMove", [target])
    page.wait_for_function("Bygga.cursor?.x===4 && Bygga.cursor?.y===1")
    assert page.evaluate("Bygga.cursor") == {"x": 4, "y": 1}
    assert page.locator("#drag-piece").is_visible()
    capture_screenshot(page, f"/tmp/bygga-rotation-touch-{width}.png")
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 1
    assert page.evaluate("[12,20,28].map(i=>Bygga.game.board[i])") == [4, 4, 4]
    # Ending the primary contact while two fingers are down also cannot drop.
    fixture(page, "g.tray[0]={shape:'line3-0',color:4};")
    touch_event(cdp, "touchStart", [origin])
    touch_event(cdp, "touchMove", [first])
    touch_event(cdp, "touchStart", [first, second])
    touch_event(cdp, "touchMove", [first, turned])
    page.wait_for_function("Bygga.game.tray[0].rotation===1")
    touch_event(cdp, "touchEnd", [first])
    touch_event(cdp, "touchEnd", [])
    assert page.evaluate("Bygga.game.moves") == 0
    assert page.locator("#drag-piece").is_hidden()
    assert page.evaluate("window.scrollY") == 0
    assert not errors, errors
    page.close()
    print(f"PASS native two-finger twist both directions, safe release order, rotate-drag-place {width}×{height}", flush=True)


def check_audio_lifecycle(browser):
    page, cdp, errors, _ = open_game(browser, 390, 844, True)
    # Chromium cannot reproduce iOS routing. Exercise the optional policy API
    # with a stub, and use real contexts/gestures for the recovery lifecycle.
    page.evaluate("Object.defineProperty(navigator,'audioSession',{configurable:true,value:{type:'auto'}})")
    tap(page, cdp, "#play")
    page.wait_for_function("Bygga.sound.context?.state==='running'")
    assert page.evaluate("navigator.audioSession.type") == "playback"
    before = page.evaluate("Bygga.game.serialize()")
    page.evaluate("window.oldAudio=Bygga.sound.context")
    tap(page, cdp, "#sound")
    page.wait_for_function("oldAudio.state==='closed'")
    assert page.evaluate("Bygga.sound.context") is None
    assert page.evaluate("navigator.audioSession.type") == "auto"
    tap(page, cdp, "#sound")
    page.wait_for_function("Bygga.sound.context?.state==='running'")
    assert page.evaluate("Bygga.sound.context!==oldAudio")
    assert page.evaluate("navigator.audioSession.type") == "playback"
    # The same teardown runs on visibilitychange, including a context reporting
    # 'running'. Reopening alone stays silent; a fresh gesture starts a new graph.
    page.evaluate("""() => {
      window.oldAudio=Bygga.sound.context;
      Object.defineProperty(document,'hidden',{configurable:true,value:true});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.wait_for_function("oldAudio.state==='closed'")
    assert page.evaluate("Bygga.sound.context") is None
    assert page.evaluate("Bygga.sound.enabled")
    assert page.evaluate("navigator.audioSession.type") == "auto"
    page.evaluate("""() => {
      Object.defineProperty(document,'hidden',{configurable:true,value:false});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    assert page.evaluate("Bygga.sound.context") is None
    tap(page, cdp, '[data-slot="0"]')
    before["tray"][0]["rotation"] = ((before["tray"][0].get("rotation", 0) + 1) % 4)
    page.wait_for_function("Bygga.sound.context?.state==='running'")
    assert page.evaluate("Bygga.sound.context!==oldAudio")
    assert page.evaluate("Bygga.game.serialize()") == before
    # A context closed externally can recover, too.
    page.evaluate("async()=>{window.oldAudio=Bygga.sound.context;await oldAudio.close()}")
    tap(page, cdp, '[data-slot="1"]')
    before["tray"][1]["rotation"] = ((before["tray"][1].get("rotation", 0) + 1) % 4)
    page.wait_for_function("Bygga.sound.context?.state==='running'")
    assert page.evaluate("Bygga.sound.context!==oldAudio")
    # Unsupported/throwing policies do not prevent audio creation.
    tap(page, cdp, "#sound")
    page.evaluate("Object.defineProperty(navigator,'audioSession',{configurable:true,value:{get type(){return 'auto'},set type(v){throw Error('Unsupported policy')}}})")
    tap(page, cdp, "#sound")
    page.wait_for_function("Bygga.sound.context?.state==='running'")
    tap(page, cdp, "#sound")
    page.evaluate("delete navigator.audioSession")
    tap(page, cdp, "#sound")
    page.wait_for_function("Bygga.sound.context?.state==='running'")
    assert page.evaluate("Bygga.game.serialize()") == before
    assert not errors, errors
    page.close()
    print("PASS native-touch audio startup, playback policy, mute/return/closed-context recovery, unsupported API, saved game unchanged", flush=True)


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
    capture_screenshot(page, "/tmp/bygga-clear-preview.png")
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


def check_clear_survives_animation(browser):
    page, _, errors, _ = open_game(browser)
    page.locator("#play").click()
    fixture(page, "g.tray[0]={shape:'single-0',color:5};for(let i=1;i<8;i++)g.board[i]=2;g.board[63]=4;")
    page.keyboard.press("1"); page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
    pixels = page.evaluate("""() => {
      const c=document.querySelector('#board'),ctx=c.getContext('2d'),scale=c.width/512;
      const sample=(x,y)=>Array.from(ctx.getImageData(Math.floor((12+(x+.5)*61)*scale),Math.floor((12+(y+.5)*61)*scale),1,1).data);
      return {alpha:ctx.globalAlpha,block:sample(7,7),empty:sample(0,0),occupied:Bygga.game.board.filter(Boolean).length};
    }""")
    assert not errors, errors
    assert pixels["alpha"] == 1, pixels
    assert pixels["occupied"] == 1, pixels
    assert pixels["block"][3] == 255 and pixels["empty"][3] == 255, pixels
    assert pixels["block"][2] > pixels["empty"][2] + 60, pixels
    capture_screenshot(page, "/tmp/bygga-after-clear.png")
    page.close()
    print("PASS surviving block and empty grid remain painted after the complete clear animation", flush=True)


def play_runs(browser, demo=False, record_dir=None):
    """Play from empty boards via actual input; inspect pixels after every move."""
    import base64
    import json

    page, _, errors, _ = open_game(browser, 768 if demo else 1366, 900, background_render=demo)
    page.evaluate("""() => {
      let seed=20261030;
      Bygga.game.random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
      Bygga.game.reset();Bygga.refresh();
    }""")
    page.locator("#play").click()
    if demo:
        page.locator("#sound").click()
    frame = 0
    history = []
    if record_dir:
        record_dir.mkdir(parents=True, exist_ok=True)

    def capture():
        nonlocal frame
        if record_dir:
            # Read the actual game canvases and HUD without asking Chrome's
            # background compositor to capture the window during user input.
            shot = page.evaluate("""() => {
              const c=document.createElement('canvas');c.width=innerWidth;c.height=innerHeight;
              const ctx=c.getContext('2d');
              const bg=ctx.createRadialGradient(c.width*.5,c.height*.35,0,c.width*.5,c.height*.35,c.height*.8);
              bg.addColorStop(0,'#1d304d');bg.addColorStop(1,'#111c30');ctx.fillStyle=bg;ctx.fillRect(0,0,c.width,c.height);
              for(const el of document.querySelectorAll('.board-wrap,.piece-slot')){
                const r=el.getBoundingClientRect(),s=getComputedStyle(el);
                ctx.beginPath();ctx.roundRect(r.x,r.y,r.width,r.height,parseFloat(s.borderRadius));
                ctx.fillStyle=s.backgroundColor;ctx.fill();
                if(parseFloat(s.borderWidth)>0){ctx.strokeStyle=s.borderColor;ctx.lineWidth=1;ctx.stroke()}
              }
              for(const el of document.querySelectorAll('#board,.piece-slot canvas')){
                const r=el.getBoundingClientRect();ctx.globalAlpha=Number(getComputedStyle(el).opacity);
                ctx.drawImage(el,r.x,r.y,r.width,r.height);
              }
              ctx.globalAlpha=1;ctx.textBaseline='top';
              for(const el of document.querySelectorAll('.label,#score,#best,#combo-text,.slot-number')){
                if(!el.checkVisibility())continue;
                const r=el.getBoundingClientRect(),s=getComputedStyle(el);ctx.font=`${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;ctx.fillStyle=s.color;
                ctx.fillText(el.textContent.trim(),r.x,r.y);
              }
              return c.toDataURL('image/jpeg',.9).split(',')[1];
            }""")
            (record_dir / f"frame-{frame:05d}.jpg").write_bytes(base64.b64decode(shot))
            frame += 1

    capture()
    total_moves = total_lines = 0
    runs = 1 if demo else 3
    for run in range(runs):
        for turn in range(180):
            move = page.evaluate("""() => {
              const E=ByggaEngine,g=Bygga.game;
              if(g.over)return null;
              let best=null;
              g.tray.forEach((p,slot)=>{
                if(!p)return;
                const seen=new Set();
                for(let rotation=0;rotation<4;rotation++) {
                const shape=E.getShape({...p,rotation}),key=JSON.stringify(shape.cells);
                if(seen.has(key))continue;seen.add(key);
                for(const {x,y} of E.placements(g.board,shape)) {
                  const r=E.simulate(g.board,shape,x,y,p.color),b=r.board;
                  let concentration=0,holes=0,dead=0;
                  const stoneRows=new Set(),stoneCols=new Set();
                  b.forEach((v,i)=>{if(v===E.STONE){stoneRows.add(Math.floor(i/8));stoneCols.add(i%8)}});
                  for(let i=0;i<8;i++){
                    let row=0,col=0;
                    for(let j=0;j<8;j++){row+=!!b[i*8+j];col+=!!b[j*8+i]}
                    if(!stoneRows.has(i))concentration+=row*row;
                    if(!stoneCols.has(i))concentration+=col*col;
                  }
                  for(let i=0;i<64;i++)if(b[i]>0&&stoneRows.has(Math.floor(i/8))&&stoneCols.has(i%8))dead++;
                  for(let i=0;i<64;i++)if(!b[i]){
                    const neighbors=[];
                    if(i%8)neighbors.push(i-1);if(i%8<7)neighbors.push(i+1);
                    if(i>=8)neighbors.push(i-8);if(i<56)neighbors.push(i+8);
                    if(neighbors.every(n=>b[n]))holes++;
                  }
                  const remaining=g.tray.map((piece,i)=>i===slot?null:piece);
                  const blocked=remaining.filter(p=>p&&!E.hasMove(b,[p])).length;
                  const room=E.placements(b,E.getShape({shape:'large-square-0'})).length;
                  const value=r.count*120+concentration*.4-holes*16-blocked*180-dead*10+room*1.5+y*.01-x*.01;
                  if(!best||value>best.value)best={slot,x,y,rotation,turns:(rotation-(p.rotation||0)+4)%4,width:shape.width,height:shape.height,value,clears:r.count,moves:g.moves};
                }
                }
              });
              return best;
            }""")
            if not move:
                break
            gx, gy, unit = board_geometry(page)
            r = page.locator(f'[data-slot="{move["slot"]}"]').bounding_box()
            click_to_place = not demo and run == 1
            if click_to_place:
                page.mouse.click(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
            turns = (move["turns"] - int(click_to_place)) % 4
            for _ in range(turns):
                page.locator(f'[data-slot="{move["slot"]}"]').click(button="right")
            assert page.evaluate("slot=>Bygga.game.tray[slot].rotation||0", move["slot"]) == move["rotation"], {"move": move, "tray": page.evaluate("Bygga.game.tray")}
            capture()
            if demo:
                aim = select_with_keyboard(page, move["slot"])
                for _ in range(abs(move["x"] - aim["x"])):
                    page.keyboard.press("ArrowRight" if move["x"] > aim["x"] else "ArrowLeft")
                for _ in range(abs(move["y"] - aim["y"])):
                    page.keyboard.press("ArrowDown" if move["y"] > aim["y"] else "ArrowUp")
                capture()
                page.keyboard.press("Enter")
            elif run == 1:
                page.mouse.click(gx + (move["x"] + .5) * unit, gy + (move["y"] + .5) * unit)
            else:
                page.mouse.move(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
                page.mouse.down()
                page.mouse.move(gx + (move["x"] + move["width"] / 2) * unit,
                                gy + (move["y"] + move["height"] / 2) * unit, steps=5)
                assert page.evaluate("Bygga.cursor") == {"x": move["x"], "y": move["y"]}, {"move": move, "cursor": page.evaluate("Bygga.cursor")}
                capture()
                page.mouse.up()
            assert page.evaluate("Bygga.game.moves") == move["moves"] + 1, {"move": move, "selected": page.evaluate("Bygga.selected"), "state": page.evaluate("Bygga.game.serialize()"), "announcement": page.locator("#announcement").inner_text()}
            page.wait_for_timeout(850 if move["clears"] else 210)
            capture()
            assert not errors, errors
            rendered = page.evaluate("""() => {
              const c=document.querySelector('#board'),ctx=c.getContext('2d'),scale=c.width/512;
              const invisible=[];
              Bygga.game.board.forEach((color,i)=>{
                const pixel=ctx.getImageData(Math.floor((12+(i%8+.5)*61)*scale),Math.floor((12+(Math.floor(i/8)+.5)*61)*scale),1,1).data;
                if(pixel[3]!==255||(color>0&&pixel[0]+pixel[1]+pixel[2]<260))invisible.push(i);
              });
              return {alpha:ctx.globalAlpha,invisible};
            }""")
            assert rendered == {"alpha": 1, "invisible": []}, rendered
            total_moves += 1
            total_lines += move["clears"]
            state = page.evaluate("({moves:Bygga.game.moves,lines:Bygga.game.totalLines,score:Bygga.game.score,stones:Bygga.game.board.filter(v=>v===ByggaEngine.STONE).length,over:Bygga.game.over})")
            history.append({"move": move, "state": state})
            if record_dir:
                (record_dir / "moves.json").write_text(json.dumps(history, indent=2))
            if (turn + 1) % 15 == 0:
                print(f"Playing run {run+1}: {state}; all pixels intact", flush=True)
        if not demo:
            capture_screenshot(page, f"/tmp/bygga-played-run-{run+1}.png")
        print(f"PASS played run {run+1}: " + str(page.evaluate("({moves:Bygga.game.moves,lines:Bygga.game.totalLines,score:Bygga.game.score,stones:Bygga.game.board.filter(v=>v===ByggaEngine.STONE).length,over:Bygga.game.over})")), flush=True)
        if run < runs - 1:
            if page.locator("#screen").is_visible():
                page.locator("#play").click()
            else:
                page.locator("#restart").click()
                if page.locator("#restart-dialog").is_visible():
                    page.locator("#confirm-restart").click()
    assert total_lines >= 10, (total_moves, total_lines)
    if record_dir:
        (record_dir / "moves.json").write_text(json.dumps(history, indent=2))
    if demo:
        if page.locator("#screen").is_visible():
            page.locator("#screen-secondary").click()
        for _ in range(9):
            capture()
        if record_dir:
            import shutil
            shutil.copy2(record_dir / f"frame-{frame-1:05d}.jpg", "/tmp/bygga-playthrough-final.jpg")
        page.evaluate("requestAnimationFrame=__nativeFrames.request;cancelAnimationFrame=__nativeFrames.cancel")
        # Explicitly requested user-facing demonstration, not a leftover QA tab.
        TEST_PAGES.remove(page)
    else:
        page.close()
    print(f"PASS actual input playthroughs: {total_moves} placements, {total_lines} cleared lines, canvas verified after every move", flush=True)


def check_installation(browser):
    import functools
    import http.server
    import json
    import re
    import shutil
    import tempfile
    import threading

    root = Path(__file__).resolve().parents[1]

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    with tempfile.TemporaryDirectory(prefix="bygga-pwa-") as directory:
        served = Path(directory) / "bygga"
        served.mkdir()
        for filename in ["index.html", "style.css", "engine.js", "sound.js", "game.js", "install.js", "sw.js", "favicon.svg", "manifest.webmanifest"]:
            shutil.copy2(root / filename, served / filename)
        shutil.copytree(root / "icons", served / "icons")
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/bygga/"
        page, cdp, errors, _ = open_game(browser, 768, 1024, True, storage="native", url=url, offline=False)
        try:
            page.wait_for_function("navigator.serviceWorker.controller!==null")
            page.wait_for_function("navigator.serviceWorker.controller.state==='activated'")
            initial_caches = page.evaluate("async()=>await caches.keys()")
            manifest = cdp.send("Page.getAppManifest")
            assert not manifest["errors"], manifest
            data = json.loads(manifest["data"])
            assert data["display"] == "standalone" and data["name"] == "Bygga" and data["lang"] == "sv", data
            assert page.locator('link[rel="apple-touch-icon"]').get_attribute("href") == "icons/apple-touch-icon.png"
            icon = page.evaluate("""async () => {
              const image=new Image();image.src=document.querySelector('link[rel="apple-touch-icon"]').href;
              await image.decode();return [image.naturalWidth,image.naturalHeight];
            }""")
            assert icon == [180, 180], icon
            page.locator("#play").click()
            page.locator("#help").click()
            page.locator("#install-help summary").click()
            assert page.locator("#install-help").get_attribute("open") is not None
            page.locator("#help-done").click()
            fixture(page, "g.score=4999;g.random=()=>.999;g.tray[0]={shape:'single-0',color:3};")
            page.keyboard.press("1"); page.keyboard.press("Enter")
            page.keyboard.press("2"); page.keyboard.press("r")
            saved = page.evaluate("Bygga.game.serialize()")
            assert saved["moves"] == 1
            assert saved["board"][63] == -1 and saved["tray"][1]["rotation"] == 1
            # Deliver a new worker/bundle without discarding the current game.
            sw = served / "sw.js"
            updated, count = re.subn(r"const CACHE = `\$\{PREFIX\}[^`]+`;", "const CACHE = `${PREFIX}qa-update`;", sw.read_text())
            assert count == 1
            sw.write_text(updated)
            with (served / "game.js").open("a") as f:
                f.write("\nwindow.__pwaUpdate = 2;\n")
            page.evaluate("""async()=>{
              const r=await navigator.serviceWorker.getRegistration();
              const changed=new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
              await r.update();await changed;
            }""")
            page.wait_for_function("navigator.serviceWorker.controller.state==='activated'")
            keys = page.evaluate("async()=>await caches.keys()")
            assert any(k.endswith("-qa-update") for k in keys) and not set(keys).intersection(initial_caches), keys
            assert page.evaluate("async()=>{const r=await caches.match(document.querySelector('script[src^=\"game.js\"]').src);return (await r.text()).includes('window.__pwaUpdate = 2')}")
            assert page.evaluate("Bygga.game.serialize()") == saved
            page.reload()
            page.wait_for_function("window.__pwaUpdate===2")
            assert page.evaluate("Bygga.game.serialize()") == saved
            assert page.locator("#best").inner_text().replace("\u00a0", "").replace(" ", "") == str(saved["score"])
            # A scoring-rule upgrade starts fresh, unlike the routine update above.
            old_rules = page.evaluate("ByggaEngine.RULES_VERSION")
            page.evaluate("localStorage.setItem('bygga.sound','off')")
            engine = served / "engine.js"
            updated, count = re.subn(r"const RULES_VERSION = \d+;", f"const RULES_VERSION = {old_rules + 1};", engine.read_text())
            assert count == 1
            engine.write_text(updated)
            sw.write_text(sw.read_text().replace("${PREFIX}qa-update", "${PREFIX}qa-rules-update"))
            page.evaluate("""async()=>{
              const r=await navigator.serviceWorker.getRegistration();
              const changed=new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
              await r.update();await changed;
            }""")
            page.wait_for_function("navigator.serviceWorker.controller.state==='activated'")
            page.reload()
            page.wait_for_function("version=>window.Bygga&&ByggaEngine.RULES_VERSION===version", arg=old_rules + 1)
            assert page.locator("#best").inner_text() == "0"
            assert page.locator("#play").inner_text().strip() == "Spela"
            assert page.locator("#sound").get_attribute("aria-pressed") == "false"
            assert page.evaluate("Bygga.game.score") == 0
            page.locator("#play").click()
            fixture(page)
            page.keyboard.press("1"); page.keyboard.press("Enter")
            saved = page.evaluate("Bygga.game.serialize()")
            assert saved["score"] == 4
            # Stop the server too: workers have their own network context, so a
            # page-only offline flag is insufficient evidence of offline support.
            server.shutdown()
            server.server_close()
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
            cdp.send("Network.emulateNetworkConditions", {
                "offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1,
            })
            page.reload()
            page.wait_for_function("window.__pwaUpdate===2 && window.Bygga")
            assert page.evaluate("Bygga.game.serialize()") == saved
            assert page.locator("#play").inner_text().strip() == "Fortsätt"
            page.locator("#play").click()
            page.keyboard.press("2"); page.keyboard.press("Enter")
            assert page.evaluate("Bygga.game.moves") == 2
            assert not errors, errors
            print("PASS app manifest/icons, iPad install help, routine update preserves record/run, major rules update resets both, offline resume/play with server stopped", flush=True)
        finally:
            # This origin belongs only to this test, unlike the user's live site.
            page.evaluate("async()=>{for(const r of await navigator.serviceWorker.getRegistrations())await r.unregister();for(const k of await caches.keys())await caches.delete(k);localStorage.clear()}")
            page.close()
            if thread.is_alive():
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--effects-only", action="store_true")
    parser.add_argument("--clear-only", action="store_true")
    parser.add_argument("--playtest", action="store_true")
    parser.add_argument("--pwa-only", action="store_true")
    parser.add_argument("--audio-only", action="store_true")
    parser.add_argument("--experiments-only", action="store_true")
    parser.add_argument("--tap-only", action="store_true")
    parser.add_argument("--no-screenshots", action="store_true", help="Run all assertions without optional window captures")
    parser.add_argument("--background-render", action="store_true", help="Keep test animations drawing when the browser is covered")
    parser.add_argument("--demo", action="store_true", help="Leave one background playthrough tab for review")
    parser.add_argument("--record-dir", type=Path, help="Capture playthrough frames and move history")
    args = parser.parse_args()
    SCREENSHOTS = not args.no_screenshots
    BACKGROUND_RENDER = args.background_render
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        try:
            if args.tap_only:
                check_single_tap_rotation(browser, 1366, 900, False)
                check_single_tap_rotation(browser, 390, 844, True)
                check_single_tap_rotation(browser, 1024, 768, True)
                check_rotation_tap(browser, 390, 844)
                check_rotation_tap(browser, 1024, 768)
                raise SystemExit(0)
            if args.experiments_only:
                check_single_tap_rotation(browser, 1366, 900, False)
                check_single_tap_rotation(browser, 390, 844, True)
                check_single_tap_rotation(browser, 1024, 768, True)
                check_stones(browser)
                check_limited_help(browser)
                check_rules_storage(browser)
                check_rotation_mouse_keyboard(browser)
                check_rotation_tap(browser, 390, 844)
                check_rotation_tap(browser, 1024, 768)
                check_rotation_touch(browser, 390, 844)
                check_rotation_touch(browser, 1024, 768)
                raise SystemExit(0)
            if args.audio_only:
                check_audio_lifecycle(browser)
                check_audio(browser)
                check_touch(browser, 390, 844)
                raise SystemExit(0)
            if args.pwa_only:
                check_installation(browser)
                raise SystemExit(0)
            if args.playtest or args.demo:
                play_runs(browser, demo=args.demo, record_dir=args.record_dir)
                raise SystemExit(0)
            check_clear_survives_animation(browser)
            if args.clear_only:
                raise SystemExit(0)
            if not args.effects_only:
                check_single_tap_rotation(browser, 1366, 900, False)
                check_single_tap_rotation(browser, 390, 844, True)
                check_single_tap_rotation(browser, 1024, 768, True)
                check_stones(browser)
                check_limited_help(browser)
                check_rules_storage(browser)
                check_rotation_mouse_keyboard(browser)
                check_rotation_tap(browser, 390, 844)
                check_rotation_tap(browser, 1024, 768)
                check_rotation_touch(browser, 390, 844)
                check_rotation_touch(browser, 1024, 768)
                check_layouts(browser)
                check_keyboard_saves(browser)
                check_touch(browser, 390, 844)
                check_touch(browser, 1024, 768)
                check_touch(browser, 844, 390)
            check_mouse(browser)
            check_audio_lifecycle(browser)
            check_audio(browser)
        finally:
            for page in TEST_PAGES:
                if not page.is_closed():
                    page.close()
