(function () {
  'use strict';
  const E = window.ByggaEngine;
  const $ = selector => document.querySelector(selector);
  const board = $('#board'), ctx = board.getContext('2d');
  const slots = [...document.querySelectorAll('.piece-slot')];
  const floating = $('#drag-piece');
  const screen = $('#screen');
  const PAD = 12, UNIT = 61, SIDE = 512;
  const palette = [null,
    ['#83dcd1', '#50b6b1', '#2e828b'], ['#ffc980', '#efa954', '#b47138'],
    ['#aeb2fb', '#8385d8', '#5555a3'], ['#7ec1ff', '#5099dc', '#3266a4'],
    ['#fb9eaa', '#df758c', '#a84966'], ['#d0dc89', '#a6bd63', '#748d40'],
    ['#d4a3f1', '#b680d5', '#7c53a6']];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* Play without storage. */ } },
    remove(key) { try { localStorage.removeItem(key); } catch (_) { /* Play without storage. */ } },
  };
  const validBest = value => Number.isSafeInteger(Number(value)) && Number(value) >= 0 ? Number(value) : 0;
  let best = validBest(store.get('bygga.best'));
  const game = new E.Game();
  const sound = new window.ByggaSound();
  sound.enabled = store.get('bygga.sound') !== 'off';
  let restored = false;
  try { restored = game.restore(JSON.parse(store.get('bygga.save.v1'))); } catch (_) { /* Ignore a corrupt save. */ }
  if (restored) best = Math.max(best, game.score);
  let playing = false, selected = -1, cursor = null, active = null, keyboardAim = false;
  const touches = new Map();
  let twist = null;
  let lockedUntil = 0, frame = 0, effect = null, particles = [], pop = null, stonePop = null;
  let toastTimer, overTimer;
  let shownScore = game.score, scoreTween = null;
  const format = value => value.toLocaleString('sv-SE');

  function roundRect(context, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.moveTo(x + r, y);
    context.arcTo(x + width, y, x + width, y + height, r);
    context.arcTo(x + width, y + height, x, y + height, r);
    context.arcTo(x, y + height, x, y, r);
    context.arcTo(x, y, x + width, y, r);
    context.closePath();
  }
  function tile(context, x, y, unit, color, alpha = 1, scale = 1) {
    const colors = palette[color] || palette[1];
    const gap = unit * 0.055, inset = (1 - scale) * unit / 2;
    const left = x + gap + inset, top = y + gap + inset;
    const size = (unit - 2 * gap) * scale;
    if (size < 0.2 || alpha <= 0) return;
    context.save();
    context.globalAlpha *= alpha;
    // Bevels and highlights must shrink with the tile. A fixed-height bevel
    // eventually made the disappearing face negative, throwing inside save()
    // and leaving the canvas transparent for every subsequent frame.
    roundRect(context, left, top + size * .05, size, size, size * .13);
    context.fillStyle = colors[2]; context.fill();
    const gradient = context.createLinearGradient(left, top, left + size * .7, top + size);
    gradient.addColorStop(0, colors[0]); gradient.addColorStop(1, colors[1]);
    roundRect(context, left, top, size, size * .96, size * .124);
    context.fillStyle = gradient; context.fill();
    context.strokeStyle = '#ffffff30'; context.lineWidth = size * .025; context.stroke();
    roundRect(context, left + size * .13, top + size * .09, size * .74, size * .036, size * .018);
    context.fillStyle = '#ffffff40'; context.fill();
    context.restore();
  }
  function sizeCanvas(canvas, width, height) {
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    }
    return canvas.getContext('2d');
  }
  function stone(context, x, y, unit, glow = 0) {
    context.save();
    context.translate(x, y);
    context.scale(unit, unit);
    // An angular, cracked face stays distinct from the rounded colored blocks.
    context.beginPath();
    context.moveTo(.19, .09); context.lineTo(.73, .07); context.lineTo(.91, .23);
    context.lineTo(.93, .77); context.lineTo(.77, .94); context.lineTo(.21, .92);
    context.lineTo(.07, .74); context.lineTo(.08, .27); context.closePath();
    const gradient = context.createLinearGradient(0, 0, 1, 1);
    gradient.addColorStop(0, '#a2aab3'); gradient.addColorStop(.5, '#747e8b'); gradient.addColorStop(1, '#4e5867');
    context.fillStyle = gradient; context.fill();
    context.strokeStyle = '#bac3cc'; context.lineWidth = .025; context.stroke();
    context.beginPath();
    context.moveTo(.08, .65); context.lineTo(.23, .79); context.lineTo(.75, .81);
    context.lineTo(.92, .65); context.lineTo(.93, .77); context.lineTo(.77, .94);
    context.lineTo(.21, .92); context.lineTo(.07, .74); context.closePath();
    context.fillStyle = '#35404d'; context.fill();
    context.beginPath();
    context.moveTo(.54, .09); context.lineTo(.44, .32); context.lineTo(.59, .46);
    context.lineTo(.48, .70); context.moveTo(.59, .46); context.lineTo(.77, .39);
    context.strokeStyle = '#303b49'; context.lineWidth = .035; context.lineJoin = 'round'; context.stroke();
    context.beginPath(); context.moveTo(.21, .24); context.lineTo(.34, .21);
    context.moveTo(.66, .65); context.lineTo(.75, .63);
    context.strokeStyle = '#d3dae16b'; context.lineWidth = .035; context.stroke();
    if (glow > 0) {
      context.globalAlpha = glow;
      roundRect(context, .035, .035, .93, .93, .16);
      context.strokeStyle = '#e0e6ee'; context.lineWidth = .045; context.stroke();
    }
    context.restore();
  }
  function drawTray() {
    slots.forEach((slot, index) => {
      const piece = game.tray[index], shape = E.getShape(piece);
      const canvas = slot.querySelector('canvas'), rect = canvas.getBoundingClientRect();
      const c = sizeCanvas(canvas, rect.width, rect.height);
      c.setTransform(canvas.width / Math.max(rect.width, 1), 0, 0, canvas.height / Math.max(rect.height, 1), 0, 0);
      c.clearRect(0, 0, rect.width, rect.height);
      slot.disabled = !piece || game.over;
      slot.classList.toggle('empty', !piece);
      slot.classList.toggle('selected', index === selected);
      slot.classList.toggle('dragging', active?.slot === index && active.moved);
      const unavailable = !!shape && !E.hasMove(game.board, [piece]);
      slot.classList.toggle('unavailable', unavailable);
      slot.setAttribute('aria-pressed', String(index === selected));
      slot.setAttribute('aria-label', shape ? `Kloss ${index + 1}, ${shape.cells.length} rutor, ${shape.width} bred och ${shape.height} hög${unavailable ? ', får inte plats just nu' : ''}` : `Kloss ${index + 1}, använd`);
      if (!shape) return;
      const unit = Math.min(28, (rect.width - 12) / shape.width, (rect.height - 17) / shape.height);
      const x = (rect.width - shape.width * unit) / 2, y = (rect.height - shape.height * unit) / 2 - 2;
      for (const [dx, dy] of shape.cells) tile(c, x + dx * unit, y + dy * unit, unit, piece.color);
    });
  }
  function requestDraw() { if (!frame) frame = requestAnimationFrame(draw); }
  function draw(now) {
    frame = 0;
    if (scoreTween) {
      const t = Math.min(1, (now - scoreTween.start) / 320);
      shownScore = Math.round(scoreTween.from + (game.score - scoreTween.from) * (1 - (1 - t) ** 3));
      $('#score').textContent = format(shownScore);
      if (t >= 1) scoreTween = null;
    }
    const rect = board.getBoundingClientRect();
    sizeCanvas(board, rect.width, rect.height);
    ctx.setTransform(board.width / SIDE, 0, 0, board.height / SIDE, 0, 0);
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, SIDE, SIDE);
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      const cell = y * 8 + x, px = PAD + x * UNIT, py = PAD + y * UNIT;
      roundRect(ctx, px + 3, py + 3, UNIT - 6, UNIT - 6, 7);
      ctx.fillStyle = (x + y) % 2 ? '#21324d' : '#22344f'; ctx.fill();
      ctx.strokeStyle = '#90b4de08'; ctx.lineWidth = 1; ctx.stroke();
      if (game.board[cell] === E.STONE) {
        const glow = stonePop?.cells.includes(cell) ? Math.max(0, 1 - (now - stonePop.start) / 750) : 0;
        stone(ctx, px, py, UNIT, glow);
      } else if (game.board[cell]) {
        let scale = 1;
        if (pop && pop.cells.includes(cell)) {
          const t = (now - pop.start) / 190;
          if (t < 1) scale = 1 + Math.sin(t * Math.PI) * .07;
        }
        tile(ctx, px, py, UNIT, game.board[cell], 1, scale);
      }
    }
    if (cursor && selected >= 0) {
      const piece = game.tray[selected], shape = E.getShape(piece);
      const preview = game.preview(selected, cursor.x, cursor.y);
      if (shape) {
        ctx.save(); ctx.beginPath(); ctx.rect(PAD, PAD, UNIT * 8, UNIT * 8); ctx.clip();
        for (const [dx, dy] of shape.cells) {
          const x = PAD + (cursor.x + dx) * UNIT, y = PAD + (cursor.y + dy) * UNIT;
          if (preview) tile(ctx, x, y, UNIT, piece.color, .45);
          roundRect(ctx, x + 3, y + 3, UNIT - 6, UNIT - 6, 7);
          ctx.strokeStyle = preview ? '#d6faffb0' : '#fb98a998';
          ctx.lineWidth = preview ? 2 : 2.5;
          ctx.setLineDash(preview ? [] : [5, 5]); ctx.stroke(); ctx.setLineDash([]);
        }
        if (preview?.count) {
          for (const i of preview.cells) {
            const x = PAD + (i % 8) * UNIT, y = PAD + Math.floor(i / 8) * UNIT;
            roundRect(ctx, x + 3, y + 3, UNIT - 6, UNIT - 6, 7);
            ctx.fillStyle = palette[piece.color][0] + '55'; ctx.fill();
            ctx.strokeStyle = palette[piece.color][0]; ctx.lineWidth = 2; ctx.stroke();
          }
          ctx.strokeStyle = palette[piece.color][0]; ctx.shadowColor = palette[piece.color][0];
          ctx.shadowBlur = 14; ctx.lineWidth = 3;
          for (const row of preview.rows) { roundRect(ctx, PAD + 1, PAD + row * UNIT + 1, UNIT * 8 - 2, UNIT - 2, 6); ctx.stroke(); }
          for (const col of preview.columns) { roundRect(ctx, PAD + col * UNIT + 1, PAD + 1, UNIT - 2, UNIT * 8 - 2, 6); ctx.stroke(); }
        }
        ctx.restore();
      }
    }
    if (effect) {
      const t = (now - effect.start) / effect.duration;
      if (t >= 1) effect = null;
      else {
        for (const i of effect.cells) {
          const x = PAD + i % 8 * UNIT, y = PAD + Math.floor(i / 8) * UNIT;
          const fade = Math.max(0, 1 - t / .5);
          tile(ctx, x, y, UNIT, effect.beforeClear[i], fade, Math.max(.01, 1 - t * 1.8));
        }
        ctx.save(); ctx.globalAlpha = Math.max(0, 1 - t / .28);
        ctx.fillStyle = '#f3ffff'; ctx.shadowColor = '#b4f5ff'; ctx.shadowBlur = 24;
        for (const row of effect.rows) { roundRect(ctx, PAD, PAD + row * UNIT + 1, UNIT * 8, UNIT - 2, 6); ctx.fill(); }
        for (const col of effect.columns) { roundRect(ctx, PAD + col * UNIT + 1, PAD, UNIT - 2, UNIT * 8, 6); ctx.fill(); }
        ctx.restore();
      }
    }
    particles = particles.filter(p => now - p.start < p.life);
    for (const p of particles) {
      if (now < p.start) continue;
      const t = (now - p.start) / 1000, progress = t * 1000 / p.life;
      ctx.save();
      ctx.globalAlpha = (1 - progress) ** 2;
      ctx.translate(p.x + p.vx * t, p.y + p.vy * t + 140 * t * t);
      ctx.rotate(p.angle + t * p.spin);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size);
      ctx.restore();
    }
    if (pop && now - pop.start > 190) pop = null;
    if (stonePop && now - stonePop.start > 750) stonePop = null;
    if (effect || particles.length || pop || stonePop || scoreTween) requestDraw();
  }
  function announce(text) { $('#announcement').textContent = text; }
  function refresh() {
    if (reducedMotion.matches || game.score < shownScore) {
      shownScore = game.score; scoreTween = null;
    } else if (game.score !== shownScore && (!scoreTween || scoreTween.target !== game.score)) {
      scoreTween = {from: shownScore, target: game.score, start: performance.now()};
    }
    $('#score').textContent = format(shownScore);
    $('#best').textContent = format(best);
    $('#combo').hidden = game.combo === 0;
    $('#combo-text').textContent = `Kombo ×${game.combo}`;
    $('#combo').setAttribute('aria-label', `Kombo ${game.combo}. ${3 - game.misses} drag kvar för att rensa igen.`);
    document.querySelectorAll('.combo-dots i').forEach((dot, i) => dot.classList.toggle('spent', i >= 3 - game.misses));
    const filled = game.board.filter(Boolean).length;
    const stones = game.board.filter(cell => cell === E.STONE).length;
    board.setAttribute('aria-label', `Spelbräde, 8 gånger 8 rutor. ${filled} upptagna rutor.${stones ? ` ${stones} av dem är sten.` : ''}${cursor ? ` Klossens hörn: rad ${cursor.y + 1}, kolumn ${cursor.x + 1}.` : ''}`);
    drawTray(); requestDraw();
  }
  function save() {
    if (game.score > best) best = game.score;
    store.set('bygga.best', String(best));
    if (game.over) store.remove('bygga.save.v1');
    else if (playing) store.set('bygga.save.v1', JSON.stringify(game.serialize()));
  }
  function toast(title, detail) {
    clearTimeout(toastTimer);
    $('#toast strong').textContent = title;
    $('#toast span').textContent = detail;
    $('#toast').classList.add('show');
    toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 1100);
  }
  function canInteract() {
    return playing && screen.hidden && !game.over && performance.now() >= lockedUntil &&
      !$('#help-dialog').open && !$('#restart-dialog').open;
  }
  function place() {
    if (!canInteract() || !cursor) return false;
    const result = game.place(selected, cursor.x, cursor.y);
    if (!result) { sound.play('invalid'); announce('Klossen får inte plats där.'); return false; }
    const now = performance.now();
    selected = -1; cursor = null;
    save();
    if (!reducedMotion.matches) pop = {start: now, cells: E.getShape(result.piece).cells.map(([x, y]) => (y + result.y) * 8 + x + result.x)};
    if (result.count) {
      lockedUntil = now + (reducedMotion.matches ? 80 : 110);
      effect = {...result, start: now, duration: reducedMotion.matches ? 80 : 340};
      if (!reducedMotion.matches) {
        for (const i of result.cells) for (let j = 0; j < 3; j++) particles.push({
          x: PAD + (i % 8 + .5) * UNIT, y: PAD + (Math.floor(i / 8) + .5) * UNIT,
          vx: (Math.random() - .5) * 200, vy: -50 - Math.random() * 180,
          start: now + 80, life: 400 + Math.random() * 300, size: 3 + Math.random() * 5,
          color: j === 0 ? '#fff0c4' : palette[result.beforeClear[i]][0], angle: Math.random() * 6, spin: Math.random() * 9,
        });
      }
      const detail = result.allClear ? 'Helt rent!' : result.combo > 1 ? `Kombo ×${result.combo}` : result.count > 1 ? `${result.count} linjer!` : '';
      if (detail) toast(detail, result.allClear ? '+300 bonus' : '');
      $('#points').textContent = `+${format(result.gain)}`;
      $('#points').classList.remove('fly');
      void $('#points').offsetWidth;
      $('#points').classList.add('fly');
      if (result.allClear) {
        $('.board-wrap').classList.remove('all-clear');
        void board.offsetWidth;
        $('.board-wrap').classList.add('all-clear');
      }
      sound.play(result.allClear ? 'allclear' : 'clear', result.combo + result.count - 1);
      announce(`${result.count} ${result.count === 1 ? 'linje rensad' : 'linjer rensade'}. ${result.gain} poäng. ${detail}`);
    } else {
      sound.play('place');
      announce(`Kloss placerad. ${game.score} poäng.`);
    }
    if (result.stones.length) {
      if (!reducedMotion.matches) stonePop = {start: now, cells: result.stones};
      toast(result.stones.length === 1 ? 'En ruta blev sten' : `${result.stones.length} rutor blev sten`, 'Sten blockerar rader och kolumner');
      const locations = result.stones.map(i => `rad ${Math.floor(i / 8) + 1}, kolumn ${i % 8 + 1}`).join('; ');
      announce(`${$('#announcement').textContent} Ny sten: ${locations}.`);
    }
    refresh();
    if (game.over) {
      clearTimeout(overTimer);
      overTimer = setTimeout(showOver, result.count ? 850 : 500);
    }
    return true;
  }
  function geometry() {
    const r = board.getBoundingClientRect(), scale = r.width / SIDE;
    return {x: r.left + PAD * scale, y: r.top + PAD * scale, unit: UNIT * scale};
  }
  function aim(x, y) {
    if (cursor?.x === x && cursor?.y === y) return;
    cursor = {x, y};
    if (active?.moved && game.preview(selected, x, y)) sound.play('tick');
    requestDraw();
  }
  function select(slot, keyboard = false) {
    if (!canInteract() || !game.tray[slot]) return;
    selected = slot;
    keyboardAim = keyboard;
    cursor = null;
    if (keyboard) {
      const spots = E.placements(game.board, E.getShape(game.tray[slot]));
      cursor = spots[0] || {x: 0, y: 0};
      board.focus({preventScroll: true});
    }
    sound.play('pick'); refresh();
  }
  function cancelPointer(clearSelection = false) {
    const previous = active;
    active = null; twist = null; keyboardAim = false; touches.clear();
    if (previous?.element.hasPointerCapture(previous.id)) previous.element.releasePointerCapture(previous.id);
    floating.hidden = true;
    if (clearSelection) selected = -1;
    cursor = null;
    refresh();
  }
  function rotateSelected(direction = 1) {
    if (!canInteract() || !game.rotate(selected, direction)) return;
    const shape = E.getShape(game.tray[selected]);
    if (cursor) cursor = {x: Math.min(cursor.x, 8 - shape.width), y: Math.min(cursor.y, 8 - shape.height)};
    if (active?.moved) positionPointer({pointerId: active.id, clientX: active.lastX, clientY: active.lastY});
    sound.unlock(); sound.play('pick'); save(); refresh();
    announce(`Kloss ${selected + 1} vriden ${direction === 1 ? 'medurs' : 'moturs'}. ${shape.width} bred och ${shape.height} hög.`);
  }
  function positionPointer(event) {
    if (!active || event.pointerId !== active.id) return;
    active.lastX = event.clientX; active.lastY = event.clientY;
    const g = geometry(), shape = E.getShape(game.tray[active.slot]);
    if (!shape) { cancelPointer(true); return; }
    if (!active.moved && Math.hypot(event.clientX - active.x, event.clientY - active.y) > 6) {
      active.moved = true; drawTray();
    }
    if (active.fromBoard) {
      aim(Math.floor((event.clientX - g.x) / g.unit), Math.floor((event.clientY - g.y) / g.unit));
      return;
    }
    if (!active.moved) return;
    const touch = active.type !== 'mouse';
    const x = event.clientX - shape.width * g.unit / 2;
    const y = event.clientY - (touch ? shape.height * g.unit + 24 : shape.height * g.unit / 2);
    aim(Math.round((x - g.x) / g.unit), Math.round((y - g.y) / g.unit));
    const width = shape.width * g.unit, height = shape.height * g.unit + 4;
    floating.style.width = `${width}px`; floating.style.height = `${height}px`;
    const c = sizeCanvas(floating, width, height);
    c.setTransform(floating.width / width, 0, 0, floating.height / height, 0, 0);
    c.clearRect(0, 0, width, height);
    for (const [dx, dy] of shape.cells) tile(c, dx * g.unit, dy * g.unit, g.unit, game.tray[active.slot].color, .96);
    floating.style.transform = `translate(${x}px, ${y}px)`;
    floating.hidden = false;
  }
  function beginTwist(event) {
    if (event.pointerType !== 'touch') return;
    touches.set(event.pointerId, {x: event.clientX, y: event.clientY});
    if (twist) { twist.tap = false; return; }
    if (!active || active.type !== 'touch' || event.pointerId === active.id) return;
    const a = touches.get(active.id), b = touches.get(event.pointerId);
    if (!a) return;
    const angle = Math.hypot(b.x - a.x, b.y - a.y) >= 16 ? Math.atan2(b.y - a.y, b.x - a.x) : null;
    twist = {second: event.pointerId, angle, turn: 0,
      start: event.timeStamp, origins: [a, b], tap: !active.moved && !active.fromBoard && touches.size === 2};
    active.suppressDrop = true;
  }
  function trackTouch(event) {
    if (touches.has(event.pointerId)) touches.set(event.pointerId, {x: event.clientX, y: event.clientY});
    if (active && twist?.tap) {
      const points = [touches.get(active.id), touches.get(twist.second)];
      if (points.some((point, i) => !point || Math.hypot(point.x - twist.origins[i].x, point.y - twist.origins[i].y) > 12)) {
        twist.tap = false;
      }
    }
  }
  function movePointer(event) {
    trackTouch(event);
    if (active && twist) {
      const a = touches.get(active.id), b = touches.get(twist.second);
      if (a && b && Math.hypot(b.x - a.x, b.y - a.y) >= 16) {
        const angle = Math.atan2(b.y - a.y, b.x - a.x);
        if (twist.angle !== null) twist.turn += Math.atan2(Math.sin(angle - twist.angle), Math.cos(angle - twist.angle));
        twist.angle = angle;
        // Snap in quarter turns, with hysteresis so small finger jitter cannot
        // immediately undo a rotation. Lifting a finger never places a piece.
        while (Math.abs(twist.turn) >= Math.PI / 3) {
          const direction = Math.sign(twist.turn);
          twist.turn -= direction * Math.PI / 2;
          twist.tap = false;
          rotateSelected(direction);
        }
      }
    } else if (active?.suppressDrop && event.pointerId === active.id && active.resume &&
        Math.hypot(event.clientX - active.resume.x, event.clientY - active.resume.y) > 6) {
      active.suppressDrop = false;
    }
    positionPointer(event);
  }
  function startPointer(event, slot, fromBoard = false) {
    if (!canInteract() || active || event.button !== 0) return;
    event.preventDefault(); sound.unlock();
    keyboardAim = false;
    if (!fromBoard) select(slot);
    if (selected < 0) return;
    active = {id: event.pointerId, slot: selected, x: event.clientX, y: event.clientY,
      lastX: event.clientX, lastY: event.clientY,
      type: event.pointerType, element: event.currentTarget, fromBoard, moved: false};
    event.currentTarget.setPointerCapture(event.pointerId);
    if (fromBoard) movePointer(event);
  }
  function endPointer(event) {
    trackTouch(event);
    if (twist && (event.pointerId === active?.id || event.pointerId === twist.second)) {
      // A brief, still two-finger tap is the touch equivalent of right-click.
      // Resolve it on the first release so either release order rotates once.
      if (twist.tap && event.timeStamp - twist.start <= 400) rotateSelected();
      twist = null;
      if (active && event.pointerId !== active.id) active.resume = touches.get(active.id);
    }
    touches.delete(event.pointerId);
    if (!active || event.pointerId !== active.id) return;
    event.preventDefault();
    sound.unlock();
    const commit = !active.suppressDrop && (active.moved || active.fromBoard);
    if (commit) positionPointer(event);
    if (commit) place();
    cancelPointer();
  }
  slots.forEach((slot, index) => {
    slot.addEventListener('pointerdown', event => startPointer(event, index));
    slot.addEventListener('contextmenu', event => {
      event.preventDefault();
      if (!canInteract() || active) return;
      select(index); rotateSelected();
    });
    slot.addEventListener('click', event => {
      if (event.detail === 0) { sound.unlock(); select(index, true); }
    });
  });
  board.addEventListener('pointerdown', event => startPointer(event, selected, true));
  board.addEventListener('pointermove', event => {
    if (active || selected < 0 || event.pointerType !== 'mouse' || !canInteract()) return;
    keyboardAim = false;
    const g = geometry();
    aim(Math.floor((event.clientX - g.x) / g.unit), Math.floor((event.clientY - g.y) / g.unit));
  });
  board.addEventListener('pointerleave', () => { if (!active && !keyboardAim) { cursor = null; requestDraw(); } });
  document.addEventListener('pointerdown', beginTwist);
  document.addEventListener('pointermove', movePointer);
  document.addEventListener('pointerup', endPointer);
  // Some iOS versions grant audio activation at touchend rather than pointerdown.
  document.addEventListener('touchend', () => { if (playing && !document.hidden) sound.unlock(); }, {passive: true});
  document.addEventListener('pointercancel', event => {
    touches.delete(event.pointerId);
    if (active?.id === event.pointerId || twist?.second === event.pointerId) cancelPointer();
  });
  document.addEventListener('lostpointercapture', event => { if (active?.id === event.pointerId) cancelPointer(); });
  document.addEventListener('contextmenu', event => event.preventDefault());
  document.addEventListener('dragstart', event => event.preventDefault());

  function start(newGame = false) {
    clearTimeout(overTimer); clearTimeout(toastTimer);
    cancelPointer(true);
    if (newGame || game.over) game.reset();
    playing = true; restored = false;
    screen.hidden = true;
    document.querySelector('.game').inert = false;
    particles = []; pop = null; stonePop = null; effect = null; lockedUntil = 0;
    $('#toast').classList.remove('show');
    sound.unlock(); sound.play('start');
    save(); refresh();
    board.focus({preventScroll: true});
  }
  function showOver() {
    cancelPointer(true);
    screen.classList.add('over');
    $('#screen-title').textContent = 'Slut på plats';
    $('#screen-copy').textContent = game.score >= best && game.score > 0 ? 'Ditt bästa bygge hittills!' : 'En kloss till får inte plats.\nDags för ett nytt bygge?';
    $('#final-score').textContent = format(game.score);
    $('#final-best').textContent = format(best);
    $('#final-stats').hidden = false;
    $('#play').firstChild.textContent = 'Spela igen ';
    $('#screen-secondary').hidden = false;
    $('#screen-secondary').textContent = 'Visa brädet';
    screen.hidden = false;
    document.querySelector('.game').inert = true;
    sound.play('over');
    $('#play').focus({preventScroll: true});
    announce(`Slut på plats. ${game.score} poäng. Rekord ${best}.`);
  }
  $('#play').addEventListener('click', () => start(game.over));
  $('#screen-secondary').addEventListener('click', () => {
    if (game.over) { screen.hidden = true; document.querySelector('.game').inert = false; $('#restart').focus(); }
    else {
      $('#restart-dialog').showModal();
    }
  });
  function syncSound() {
    $('#sound').setAttribute('aria-pressed', String(sound.enabled));
    $('#sound').setAttribute('aria-label', sound.enabled ? 'Stäng av ljud' : 'Slå på ljud');
    $('#sound-waves').setAttribute('d', sound.enabled ? 'M16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14' : 'm16 9 6 6m0-6-6 6');
  }
  $('#sound').addEventListener('click', () => {
    sound.setEnabled(!sound.enabled);
    store.set('bygga.sound', sound.enabled ? 'on' : 'off');
    syncSound(); if (sound.enabled) sound.play('pick');
  });
  $('#help').addEventListener('click', () => { cancelPointer(true); $('#help-dialog').showModal(); });
  $('#close-help').addEventListener('click', () => $('#help-dialog').close());
  $('#help-done').addEventListener('click', () => $('#help-dialog').close());
  $('#restart').addEventListener('click', () => {
    cancelPointer(true);
    if (game.over || !game.moves) start(true);
    else $('#restart-dialog').showModal();
  });
  $('#confirm-restart').addEventListener('click', () => { $('#restart-dialog').close(); start(true); });
  $('#cancel-restart').addEventListener('click', () => $('#restart-dialog').close());
  document.addEventListener('keydown', event => {
    if ($('#help-dialog').open || $('#restart-dialog').open) return;
    if (!screen.hidden) {
      if (event.key === 'Enter' && event.target === document.body) { event.preventDefault(); start(game.over); }
      return;
    }
    if (!canInteract() || active) return;
    if (event.key === 'Escape') { event.preventDefault(); cancelPointer(true); return; }
    if (/^[123]$/.test(event.key)) {
      event.preventDefault(); sound.unlock(); select(Number(event.key) - 1, true); return;
    }
    if (event.key.toLowerCase() === 'r') {
      event.preventDefault(); rotateSelected(event.shiftKey ? -1 : 1); return;
    }
    if (event.key.startsWith('Arrow')) {
      event.preventDefault(); sound.unlock();
      if (selected < 0) select(game.tray.findIndex(Boolean), true);
      if (selected < 0) return;
      keyboardAim = true;
      const shape = E.getShape(game.tray[selected]);
      const {x, y} = cursor || {x: 0, y: 0};
      aim(Math.max(0, Math.min(8 - shape.width, x + (event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0))),
        Math.max(0, Math.min(8 - shape.height, y + (event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0))));
      refresh();
    } else if ((event.key === 'Enter' || event.key === ' ') && event.target === board && selected >= 0) {
      event.preventDefault(); sound.unlock(); place();
    }
  });
  function resize() { cancelPointer(); }
  new ResizeObserver(resize).observe(board);
  window.addEventListener('blur', () => cancelPointer());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelPointer(); if (playing) save(); sound.suspend(); }
  });
  window.addEventListener('pagehide', () => { if (playing) save(); sound.suspend(); });
  window.addEventListener('storage', event => {
    if (event.key === 'bygga.best') { best = Math.max(best, validBest(event.newValue)); refresh(); }
  });
  syncSound(); refresh();
  document.querySelector('.game').inert = true;
  if (restored) {
    $('#screen-copy').textContent = `Ditt bygge väntar.\n${format(game.score)} poäng hittills.`;
    $('#play').firstChild.textContent = 'Fortsätt ';
    $('#screen-secondary').hidden = false;
    $('#screen-secondary').textContent = 'Nytt spel';
  }
  // The pure engine and refresh entry point also make saved positions inspectable.
  window.Bygga = {game, sound, refresh, get selected() { return selected; }, get cursor() { return cursor; }};
})();
