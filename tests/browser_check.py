# /// script
# requires-python = ">=3.11, <3.14"
# dependencies = ["playwright==1.63.0"]
# ///
"""Offline gameplay checks in isolated background tabs of the existing Chrome."""
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()
TEST_PAGES = []


def open_game(browser, width=1366, height=900, touch=False, storage=True, url=URL, offline=True):
    context = browser.contexts[0]
    browser_cdp = browser.new_browser_cdp_session()
    with context.expect_page() as created:
        browser_cdp.send("Target.createTarget", {
            "url": "about:blank", "background": True, "newWindow": False,
        })
    page = created.value
    TEST_PAGES.append(page)
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
        "offline": offline, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1,
    })
    if storage is True:
        page.add_init_script("""(() => {
          const values=window.name ? JSON.parse(window.name) : {'bygga.best':'42'};
          Object.defineProperty(window,'localStorage',{value:{
            getItem:key=>values[key]??null,
            setItem:(key,value)=>{values[key]=String(value);window.name=JSON.stringify(values)},
            removeItem:key=>{delete values[key];window.name=JSON.stringify(values)}
          }});
        })()""")
    elif storage is False:
        page.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('Storage disabled')}})")
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda req: requests.append(req.url) if req.url.startswith("http") else None)
    page.goto(url)
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
    page.screenshot(path="/tmp/bygga-after-clear.png")
    page.close()
    print("PASS surviving block and empty grid remain painted after the complete clear animation", flush=True)


def play_runs(browser):
    """Play from empty boards via actual input; inspect pixels after every move."""
    page, _, errors, _ = open_game(browser)
    page.locator("#play").click()
    total_moves = total_lines = 0
    for run in range(3):
        for turn in range(45):
            move = page.evaluate("""() => {
              const E=ByggaEngine,g=Bygga.game;
              if(g.over)return null;
              let best=null;
              g.tray.forEach((p,slot)=>{
                if(!p)return;
                const shape=E.getShape(p);
                for(const {x,y} of E.placements(g.board,shape)) {
                  const r=g.preview(slot,x,y),b=r.board;
                  let concentration=0,holes=0;
                  for(let i=0;i<8;i++){
                    let row=0,col=0;
                    for(let j=0;j<8;j++){row+=!!b[i*8+j];col+=!!b[j*8+i]}
                    concentration+=row*row+col*col;
                  }
                  for(let i=0;i<64;i++)if(!b[i]){
                    const neighbors=[];
                    if(i%8)neighbors.push(i-1);if(i%8<7)neighbors.push(i+1);
                    if(i>=8)neighbors.push(i-8);if(i<56)neighbors.push(i+8);
                    if(neighbors.every(n=>b[n]))holes++;
                  }
                  const remaining=g.tray.map((piece,i)=>i===slot?null:piece);
                  const blocked=remaining.filter(p=>p&&!E.placements(b,E.getShape(p)).length).length;
                  const value=r.count*100+concentration*.2-holes*12-blocked*90+y*.01-x*.01;
                  if(!best||value>best.value)best={slot,x,y,width:shape.width,height:shape.height,value,clears:r.count,moves:g.moves};
                }
              });
              return best;
            }""")
            if not move:
                break
            gx, gy, unit = board_geometry(page)
            r = page.locator(f'[data-slot="{move["slot"]}"]').bounding_box()
            if run == 1:
                page.mouse.click(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
                page.mouse.click(gx + (move["x"] + .5) * unit, gy + (move["y"] + .5) * unit)
            else:
                page.mouse.move(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
                page.mouse.down()
                page.mouse.move(gx + (move["x"] + move["width"] / 2) * unit,
                                gy + (move["y"] + move["height"] / 2) * unit, steps=5)
                assert page.evaluate("Bygga.cursor") == {"x": move["x"], "y": move["y"]}, {"move": move, "cursor": page.evaluate("Bygga.cursor")}
                page.mouse.up()
            assert page.evaluate("Bygga.game.moves") == move["moves"] + 1, {"move": move, "selected": page.evaluate("Bygga.selected")}
            page.wait_for_timeout(850 if move["clears"] else 210)
            assert not errors, errors
            rendered = page.evaluate("""() => {
              const c=document.querySelector('#board'),ctx=c.getContext('2d'),scale=c.width/512;
              const invisible=[];
              Bygga.game.board.forEach((color,i)=>{
                const pixel=ctx.getImageData(Math.floor((12+(i%8+.5)*61)*scale),Math.floor((12+(Math.floor(i/8)+.5)*61)*scale),1,1).data;
                if(pixel[3]!==255||(color&&pixel[0]+pixel[1]+pixel[2]<260))invisible.push(i);
              });
              return {alpha:ctx.globalAlpha,invisible};
            }""")
            assert rendered == {"alpha": 1, "invisible": []}, rendered
            total_moves += 1
            total_lines += move["clears"]
            if (turn + 1) % 15 == 0:
                print(f"Playing run {run+1}: {turn+1} moves; {total_lines} lines cleared across runs; all pixels intact", flush=True)
        page.screenshot(path=f"/tmp/bygga-played-run-{run+1}.png")
        print(f"PASS played run {run+1}: " + str(page.evaluate("({moves:Bygga.game.moves,lines:Bygga.game.totalLines,score:Bygga.game.score,over:Bygga.game.over})")), flush=True)
        if run < 2:
            if page.locator("#screen").is_visible():
                page.locator("#play").click()
            else:
                page.locator("#restart").click()
                if page.locator("#restart-dialog").is_visible():
                    page.locator("#confirm-restart").click()
    assert total_lines >= 10, (total_moves, total_lines)
    page.close()
    print(f"PASS actual input playthroughs: {total_moves} placements, {total_lines} cleared lines, canvas verified after every move", flush=True)


def check_installation(browser):
    import functools
    import http.server
    import json
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
            page.keyboard.press("1"); page.keyboard.press("Enter")
            saved = page.evaluate("Bygga.game.serialize()")
            assert saved["moves"] == 1
            # Deliver a new worker/bundle without discarding the current game.
            sw = served / "sw.js"
            sw.write_text(sw.read_text().replace("${PREFIX}v1", "${PREFIX}v2"))
            with (served / "game.js").open("a") as f:
                f.write("\nwindow.__pwaUpdate = 2;\n")
            page.evaluate("""async()=>{
              const r=await navigator.serviceWorker.getRegistration();
              const changed=new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
              await r.update();await changed;
            }""")
            page.wait_for_function("navigator.serviceWorker.controller.state==='activated'")
            keys = page.evaluate("async()=>await caches.keys()")
            assert any(k.endswith("-v2") for k in keys) and not any(k.endswith("-v1") for k in keys), keys
            assert page.evaluate("async()=>{const r=await caches.match(new URL('game.js?v=2',location.href));return (await r.text()).includes('window.__pwaUpdate = 2')}")
            assert page.evaluate("Bygga.game.serialize()") == saved
            page.reload()
            page.wait_for_function("window.__pwaUpdate===2")
            assert page.evaluate("Bygga.game.serialize()") == saved
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
            print("PASS app manifest/icons, iPad install help, worker update preserves game, offline cold reload/play with server stopped", flush=True)
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
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        try:
            if args.pwa_only:
                check_installation(browser)
                raise SystemExit(0)
            if args.playtest:
                play_runs(browser)
                raise SystemExit(0)
            check_clear_survives_animation(browser)
            if args.clear_only:
                raise SystemExit(0)
            if not args.effects_only:
                check_layouts(browser)
                check_keyboard_saves(browser)
                check_touch(browser, 390, 844)
                check_touch(browser, 1024, 768)
                check_touch(browser, 844, 390)
            check_mouse(browser)
            check_audio(browser)
        finally:
            for page in TEST_PAGES:
                if not page.is_closed():
                    page.close()
