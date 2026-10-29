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
function solve(board, tray) {
  if (tray.every(p => !p)) return [];
  for (let slot = 0; slot < tray.length; slot++) {
    if (!tray[slot]) continue;
    const shape = E.getShape(tray[slot]);
    for (const {x, y} of E.placements(board, shape)) {
      const remaining = tray.slice(); remaining[slot] = null;
      const rest = solve(E.simulate(board, shape, x, y).board, remaining);
      if (rest) return [{slot, x, y}, ...rest];
    }
  }
  return null;
}

test('catalog has distinct occupied cells, normalized fixed orientations and all basic shapes', () => {
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
test('dealt trays have an actual three-placement solution even on crowded boards', () => {
  const random = rng(12);
  let b = E.emptyBoard();
  for (let i = 0; i < 32; i++) {
    const before = b.slice(), tray = E.deal(b, random);
    assert.deepEqual(b, before, 'Dealing must not alter the real board');
    assert.equal(tray.length, 3); assert(solve(b, tray), `Unsolvable tray ${i}`);
    // Choose any legal move, not the dealer's hidden construction.
    const legal = tray.flatMap(p => E.placements(b, E.getShape(p)).map(spot => ({...spot, p})));
    const move = legal[Math.floor(random() * legal.length)];
    b = E.simulate(b, E.getShape(move.p), move.x, move.y).board;
  }
});
test('long seeded runs preserve board, score and legal end-state invariants', () => {
  const random = rng(321);
  for (let run = 0; run < 12; run++) {
    const g = new E.Game(random);
    for (let turn = 0; turn < 180 && !g.over; turn++) {
      const legal = g.tray.flatMap((p, slot) => p ? E.placements(g.board, E.getShape(p)).map(spot => ({slot, ...spot})) : []);
      assert(legal.length);
      const move = legal[Math.floor(random() * legal.length)];
      const previous = g.score;
      assert(g.place(move.slot, move.x, move.y)); assert(g.score > previous);
      assert.equal(E.lines(g.board).count, 0);
      assert.equal(g.board.length, 64);
      assert(g.board.every(c => Number.isInteger(c) && c >= 0 && c <= 7));
      assert.equal(g.over, !E.hasMove(g.board, g.tray));
    }
  }
});
