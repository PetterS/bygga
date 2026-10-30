const {test} = require('node:test');
const assert = require('node:assert/strict');
const E = require('../engine.js');

function rng(seed = 2026) {
  return () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
}
const piece = (shape = 'single-0', color = 1) => ({shape, color});
function position(board = E.emptyBoard(), tray = [piece(), piece(), piece()]) {
  const game = new E.Game(rng()); game.board = board; game.tray = tray; return game;
}
test('catalog has distinct occupied cells, normalized orientations and all basic shapes', () => {
  assert(E.SHAPES.length >= 35);
  assert.equal(E.getShape(piece('large-square-0')).cells.length, 9);
  assert.equal(E.getShape(piece('line5-1')).height, 5);
  for (const s of E.SHAPES) {
    assert.equal(new Set(s.cells.map(String)).size, s.cells.length);
    assert.equal(Math.min(...s.cells.map(c => c[0])), 0);
    assert.equal(Math.min(...s.cells.map(c => c[1])), 0);
    assert(s.cells.every(([x, y]) => x < s.width && y < s.height));
  }
});
test('placement rejects overlap, edges, noninteger input and consumed slots without mutation', () => {
  const g = position(); g.tray[0] = piece('square-0'); g.board[0] = 2;
  const before = g.serialize();
  for (const [slot, x, y] of [[0, 0, 0], [0, -1, 0], [0, 7, 0], [0, 0, 7], [0, 1.5, 0], [5, 1, 1], [0, NaN, 0]]) {
    assert.equal(g.place(slot, x, y), null); assert.deepEqual(g.serialize(), before);
  }
  assert(g.place(0, 2, 2)); assert.equal(g.place(0, 4, 4), null);
});
test('sparse shapes need only occupied cells to fit', () => {
  const b = E.emptyBoard(); b[1] = 2; b[8] = 3;
  assert(E.fits(b, E.getShape(piece('diagonal-0')), 0, 0));
  assert(!E.fits(b, E.getShape(piece('square-0')), 0, 0));
});
test('crossing row and column clear simultaneously and intersection counts once', () => {
  const b = E.emptyBoard();
  for (let i = 1; i < 8; i++) { b[i] = 2; b[i * 8] = 3; }
  b[63] = 5;
  const g = position(b), preview = g.preview(0, 0, 0);
  assert.equal(preview.count, 2); assert.equal(preview.cells.length, 15);
  assert.equal(g.board[0], 0, 'Preview cannot mutate the board');
  const result = g.place(0, 0, 0);
  assert.equal(result.gain, 401); assert.equal(g.combo, 1); assert.equal(g.totalLines, 2);
  assert.equal(g.board.filter(Boolean).length, 1); assert.equal(g.board[63], 5);
});
test('all clear bonus, simultaneous multiple rows and score are exact', () => {
  const b = E.emptyBoard();
  for (let y = 0; y < 3; y++) for (let x = 1; x < 8; x++) b[y * 8 + x] = 1;
  const g = position(b, [piece('line3-1'), piece(), piece()]);
  const result = g.place(0, 0, 0);
  assert.equal(result.count, 3); assert(result.allClear);
  assert.equal(result.gain, 3 + 900 + 300); assert(g.board.every(c => !c));
});
test('two non-clears preserve a chain, third breaks it; invalid attempts do not count', () => {
  const g = position(); g.combo = 2;
  g.place(0, 0, 0); g.place(1, 1, 0);
  assert.equal(g.combo, 2); assert.equal(g.misses, 2);
  assert.equal(g.place(2, 0, 0), null); assert.equal(g.misses, 2);
  for (let x = 2; x < 7; x++) g.board[x] = 1;
  const result = g.place(2, 7, 0);
  assert.equal(result.combo, 3); assert.equal(g.misses, 0);
  g.tray = [piece(), piece(), piece()];
  g.place(0, 0, 0); g.place(1, 1, 0); g.place(2, 2, 0);
  assert.equal(g.combo, 0); assert.equal(g.misses, 0);
});
test('only refill after all three pieces are used, any order is legal', () => {
  const g = position();
  assert(!g.place(2, 0, 0).refill); assert.equal(g.tray[2], null);
  assert(!g.place(0, 1, 0).refill); assert.equal(g.tray[0], null);
  assert(g.place(1, 2, 0).refill); assert(g.tray.every(Boolean));
});
test('game ends only when every remaining piece fails, even if a larger piece is blocked', () => {
  const b = Array.from({length: 64}, (_, i) => (Math.floor(i / 8) + i % 8) % 2 ? 1 : 0);
  const g = position(b, [piece(), piece('square-0'), piece('line2-0')]);
  assert(E.hasMove(g.board, g.tray));
  g.place(0, 0, 0);
  assert(g.over); assert.equal(g.place(1, 3, 3), null);
});
test('a line clear may unlock a piece that previously did not fit', () => {
  const b = Array.from({length: 64}, (_, i) => (Math.floor(i / 8) + i % 8) % 2 ? 1 : 0);
  for (let x = 0; x < 8; x++) b[x] = x ? 1 : 0;
  const g = position(b, [piece(), piece('line5-0'), null]);
  assert.equal(E.placements(b, E.getShape(g.tray[1])).length, 0);
  g.place(0, 0, 0); assert(!g.over);
  assert(E.placements(g.board, E.getShape(g.tray[1])).length > 0);
});
test('stones reject placement and block their row and column without blocking other clears', () => {
  const b = E.emptyBoard();
  for (let i = 0; i < 8; i++) { b[i] = 2; b[i * 8] = 3; b[i * 8 + 3] = 4; }
  b[0] = E.STONE; b[59] = 0;
  const g = position(b), before = g.serialize();
  assert.equal(g.preview(0, 0, 0), null);
  assert.equal(g.place(0, 0, 0), null);
  assert.deepEqual(g.serialize(), before);
  assert.equal(E.lines(b).count, 0, 'Stone cannot complete a full row or column');
  const preview = g.preview(0, 3, 7);
  assert.deepEqual(preview.rows, []); assert.deepEqual(preview.columns, [3]);
  const result = g.place(0, 3, 7);
  assert.equal(result.count, 1); assert.equal(result.gain, 101);
  assert.equal(g.board[0], E.STONE); assert.equal(g.board[1], 2); assert.equal(g.board[8], 3);
});
test('each 5000-point crossing turns an empty square to stone without replacing blocks or stones', () => {
  const g = position(); g.score = 4998; g.random = () => 0;
  assert.deepEqual(g.place(0, 0, 0).stones, []);
  assert.equal(g.score, 4999);
  assert.deepEqual(g.place(1, 1, 0).stones, [2]);
  assert.equal(g.score, 5000); assert.deepEqual(g.board.slice(0, 3), [1, 1, E.STONE]);
  assert.deepEqual(g.place(2, 3, 0).stones, []);
  g.score = 9999; g.tray = [piece(), piece(), piece()];
  assert.deepEqual(g.place(0, 4, 0).stones, [5]);
  assert.deepEqual(g.board.slice(0, 6), [1, 1, E.STONE, 1, 1, E.STONE]);
  assert.equal(g.board.filter(c => c === E.STONE).length, 2);
  g.reset(); assert.equal(g.score, 0); assert(g.board.every(c => c === 0));
});
test('one large clear awards every crossed milestone after scoring and clearing', () => {
  const b = E.emptyBoard();
  for (let y = 0; y < 3; y++) for (let x = 1; x < 8; x++) b[y * 8 + x] = 1;
  const g = position(b, [piece('line3-1'), piece(), piece()]);
  g.score = 4999; g.combo = 20; g.moves = 20; g.random = () => 0;
  const before = g.serialize();
  assert.equal(g.preview(0, 0, 0).count, 3);
  assert.deepEqual(g.serialize(), before, 'Preview cannot spawn stones');
  const result = g.place(0, 0, 0);
  assert.equal(result.gain, 3 + 900 * 21 + 300);
  assert(result.allClear, 'Bonus is determined before stones appear');
  assert.deepEqual(result.stones, [0, 1, 2, 3]);
  assert.equal(g.board.filter(c => c === E.STONE).length, 4);
  assert(g.board.every(c => c === 0 || c === E.STONE));
});
test('a new stone is considered immediately when deciding whether the game is over', () => {
  const b = Array(64).fill(E.STONE); b[0] = 0; b[1] = 0;
  const g = position(b); g.score = 4999; g.random = () => .999;
  const result = g.place(0, 0, 0);
  assert.deepEqual(result.stones, [1]);
  assert.equal(g.board[0], 1); assert.equal(g.board[1], E.STONE);
  assert(g.over); assert(!E.hasMove(g.board, g.tray));
});
test('milestones cannot overwrite occupied cells when fewer empty squares remain', () => {
  const b = Array(64).fill(E.STONE); b[0] = b[1] = 0;
  for (const empty of [0, 1]) {
    const board = b.slice(); board[1] = empty ? 0 : 2;
    const g = position(board); g.score = 4999;
    const result = g.place(0, 0, 0);
    assert.equal(result.stones.length, empty);
    assert.equal(g.board[0], 1); assert.equal(g.board[1], empty ? E.STONE : 2);
    assert(g.over);
  }
});
test('a nearly stone-filled board still deals three pieces and allows the last legal move', () => {
  const b = Array(64).fill(E.STONE); b[0] = 0; b[1] = 0;
  const g = position(b, [piece(), null, null]); g.random = () => 0;
  assert(g.place(0, 0, 0).refill);
  assert.equal(g.tray.length, 3); assert(!g.over);
  const slot = g.tray.findIndex(p => E.placements(g.board, E.getShape(p)).length);
  assert(g.place(slot, 1, 0)); assert(g.over);
});
test('stones survive save/resume and legacy saves start adding stones at their next milestone', () => {
  const g = position(); g.score = 4999; g.random = () => 0;
  g.place(0, 0, 0);
  const saved = g.serialize(), restored = new E.Game(rng());
  assert.equal(saved.version, 2);
  assert(restored.restore(saved)); assert.deepEqual(restored.serialize(), saved);
  assert.equal(restored.place(1, 0, 0), null);
  assert.equal(restored.place(1, 1, 0), null, 'The empty square became stone');
  assert.deepEqual(restored.place(1, 2, 0).stones, [], 'Reload must not repeat a milestone');
  const legacy = {...position().serialize(), version: 1, score: 9998};
  assert(restored.restore(legacy)); assert(restored.board.every(c => c === 0));
  assert.deepEqual(restored.place(0, 0, 0).stones, []);
  assert.equal(restored.place(1, 1, 0).stones.length, 1);
  assert.equal(restored.restore({...saved, version: 1}), false, 'Old format cannot contain stones');
  assert.equal(restored.restore({...saved, board: [-2, ...saved.board.slice(1)]}), false);
});
test('quarter turns normalize every shape without moving blocks, scoring or consuming a turn', () => {
  const g = position();
  for (const shape of E.SHAPES) {
    g.tray[0] = piece(shape.id, 3);
    const original = E.getShape(g.tray[0]);
    for (let i = 0; i < 4; i++) {
      assert(g.rotate(0));
      const turned = E.getShape(g.tray[0]);
      assert.equal(turned.cells.length, original.cells.length);
      assert.equal(Math.min(...turned.cells.map(c => c[0])), 0);
      assert.equal(Math.min(...turned.cells.map(c => c[1])), 0);
      assert.equal(turned.width, i % 2 ? original.width : original.height);
      assert.equal(turned.height, i % 2 ? original.height : original.width);
    }
    assert.deepEqual(E.getShape(g.tray[0]), original);
    assert(g.rotate(0, -1)); assert.equal(g.tray[0].rotation, 3);
    assert(g.rotate(0)); assert.deepEqual(E.getShape(g.tray[0]), original);
  }
  assert.equal(g.score, 0); assert.equal(g.moves, 0); assert(g.board.every(c => c === 0));
  const before = g.serialize();
  assert(!g.rotate(7)); assert(!g.rotate(0, 2)); assert.deepEqual(g.serialize(), before);
  g.over = true; assert(!g.rotate(0));
});
test('a piece that fits only after rotation keeps the game alive and can be placed between stones', () => {
  const b = Array(64).fill(E.STONE); b[0] = 0;
  for (let y = 1; y <= 4; y++) b[y * 8 + 3] = 0;
  const g = position(b, [piece(), piece('line4-0', 2), null]);
  assert(g.place(0, 0, 0)); assert(!g.over);
  assert.equal(E.placements(g.board, E.getShape(g.tray[1])).length, 0);
  assert(g.rotate(1)); assert(g.preview(1, 3, 1));
  const saved = g.serialize(), restored = new E.Game(rng());
  assert(restored.restore(saved)); assert.deepEqual(restored.serialize(), saved);
  assert(restored.place(1, 3, 1)); assert(restored.over);
  for (let y = 1; y <= 4; y++) assert.equal(restored.board[y * 8 + 3], 2);
  for (const rotation of [null, -1, 4, 1.5, '1']) {
    const invalid = {...saved, tray: [null, {...saved.tray[1], rotation}, null]};
    assert(!g.restore(invalid));
  }
});
test('save roundtrip clones state and rejects corrupt or impossible saves', () => {
  const g = position(); g.place(0, 0, 0);
  const saved = g.serialize(), restored = new E.Game(rng());
  assert(restored.restore(saved)); assert.deepEqual(restored.serialize(), saved);
  saved.board[1] = 7; assert.equal(restored.board[1], 0);
  for (const bad of [null, {}, {...g.serialize(), version: 4}, {...g.serialize(), score: Infinity},
    {...g.serialize(), board: []}, {...g.serialize(), board: Array(64).fill(1)},
    {...g.serialize(), tray: [piece('absent'), null, null]}, {...g.serialize(), tray: [null, null, null]},
    {...g.serialize(), combo: 400}, {...g.serialize(), misses: 3}]) {
    assert.equal(restored.restore(bad), false);
  }
});
test('dealt trays offer an opening move even in a single isolated empty square', () => {
  const random = rng(12);
  for (let i = 0; i < 64; i++) {
    const b = Array(64).fill(E.STONE); b[i] = 0;
    const before = b.slice(), tray = E.deal(b, random);
    assert.deepEqual(b, before, 'Dealing must not alter the real board');
    assert.equal(tray.length, 3); assert(E.hasMove(b, tray), `No opening move at ${i}`);
  }
  const full = Array(64).fill(E.STONE), tray = E.deal(full, random);
  assert.equal(tray.length, 3); assert(!E.hasMove(full, tray));
});
test('two-row trap still deals unrestricted corners and squares and can end after its opening move', () => {
  const b = Array.from({length: 64}, (_, i) => {
    const x = i % 8, y = Math.floor(i / 8);
    return y === 0 || y === 7 ? 0 : (x + y) % 3 === 0 ? E.STONE : 1;
  });
  const rolls = [0, 0, .95, 0, .25, 0, .999, .999];
  const tray = E.deal(b, () => rolls.shift());
  assert.equal(tray[0].shape, 'single-0');
  assert(tray[1].shape.startsWith('big-corner-'));
  assert.equal(tray[2].shape, 'square-0');
  assert(E.hasMove(b, [tray[0]]));
  assert(!E.hasMove(b, [tray[1], tray[2]]), 'The other two pieces must not be filtered by fit');
  const g = position(b, tray);
  assert(g.place(0, 0, 0)); assert(g.over);
});
test('a refill guarantees its opening move after the new stone has appeared', () => {
  const b = Array(64).fill(E.STONE); b[0] = b[1] = b[2] = 0;
  const g = position(b, [piece(), null, null]); g.score = 4999; g.random = () => .999;
  const result = g.place(0, 0, 0);
  assert.deepEqual(result.stones, [2]); assert(result.refill);
  assert(E.hasMove(g.board, g.tray)); assert(!g.over);
});
test('long seeded runs preserve board, score and legal end-state invariants', () => {
  const random = rng(321);
  for (let run = 0; run < 12; run++) {
    const g = new E.Game(random);
    for (let turn = 0; turn < 180 && !g.over; turn++) {
      const legal = g.tray.flatMap((p, slot) => p ? Array.from({length: 4}, (_, rotation) =>
        E.placements(g.board, E.getShape({...p, rotation})).map(spot => ({slot, rotation, ...spot}))).flat() : []);
      assert(legal.length);
      const move = legal[Math.floor(random() * legal.length)];
      const previous = g.score;
      while ((g.tray[move.slot].rotation || 0) !== move.rotation) assert(g.rotate(move.slot));
      assert(g.place(move.slot, move.x, move.y)); assert(g.score > previous);
      assert.equal(E.lines(g.board).count, 0);
      assert.equal(g.board.length, 64);
      assert(g.board.every(c => Number.isInteger(c) && c >= E.STONE && c <= 7));
      assert.equal(g.over, !E.hasMove(g.board, g.tray));
    }
  }
});
