(function (root) {
  'use strict';

  const SIZE = 8;
  const SHAPES = [];
  const byId = new Map();
  const keyOf = cells => cells.map(([x, y]) => `${x},${y}`).join(';');
  function normalize(cells) {
    const minX = Math.min(...cells.map(c => c[0]));
    const minY = Math.min(...cells.map(c => c[1]));
    return cells.map(([x, y]) => [x - minX, y - minY]).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  }
  function family(name, cells, weight, rotations = 1) {
    const seen = new Set();
    for (let r = 0; r < rotations; r++) {
      cells = normalize(cells);
      const key = keyOf(cells);
      if (!seen.has(key)) {
        seen.add(key);
        const shape = Object.freeze({id: `${name}-${r}`, cells: Object.freeze(cells.map(Object.freeze)),
          width: Math.max(...cells.map(c => c[0])) + 1,
          height: Math.max(...cells.map(c => c[1])) + 1, weight});
        SHAPES.push(shape);
        byId.set(shape.id, shape);
      }
      cells = cells.map(([x, y]) => [-y, x]);
    }
  }
  family('single', [[0, 0]], 0.35);
  for (let n = 2; n <= 5; n++) family(`line${n}`, Array.from({length: n}, (_, x) => [x, 0]), n === 5 ? 0.75 : 1.25, 2);
  family('square', [[0, 0], [1, 0], [0, 1], [1, 1]], 2.8);
  family('rectangle', [[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]], 1.2, 2);
  family('large-square', Array.from({length: 9}, (_, i) => [i % 3, Math.floor(i / 3)]), 1.2);
  family('corner', [[0, 0], [0, 1], [1, 1]], 1.3, 4);
  family('ell', [[0, 0], [0, 1], [0, 2], [1, 2]], 1, 4);
  family('jay', [[1, 0], [1, 1], [0, 2], [1, 2]], 1, 4);
  family('tee', [[0, 0], [1, 0], [2, 0], [1, 1]], 1.2, 4);
  family('ess', [[1, 0], [2, 0], [0, 1], [1, 1]], 0.85, 2);
  family('zed', [[0, 0], [1, 0], [1, 1], [2, 1]], 0.85, 2);
  family('big-corner', [[0, 0], [0, 1], [0, 2], [1, 2], [2, 2]], 0.7, 4);
  family('diagonal', [[0, 0], [1, 1]], 0.3, 2);
  Object.freeze(SHAPES);

  const emptyBoard = () => Array(SIZE * SIZE).fill(0);
  const getShape = piece => piece && byId.get(piece.shape);
  function fits(board, shape, x, y) {
    if (!shape || !Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 ||
        x + shape.width > SIZE || y + shape.height > SIZE) return false;
    return shape.cells.every(([dx, dy]) => !board[(y + dy) * SIZE + x + dx]);
  }
  function placements(board, shape) {
    const result = [];
    for (let y = 0; y <= SIZE - shape.height; y++) {
      for (let x = 0; x <= SIZE - shape.width; x++) if (fits(board, shape, x, y)) result.push({x, y});
    }
    return result;
  }
  function lines(board) {
    const rows = [], columns = [], cells = new Set();
    for (let i = 0; i < SIZE; i++) {
      if (Array.from({length: SIZE}, (_, x) => board[i * SIZE + x]).every(Boolean)) rows.push(i);
      if (Array.from({length: SIZE}, (_, y) => board[y * SIZE + i]).every(Boolean)) columns.push(i);
    }
    for (const y of rows) for (let x = 0; x < SIZE; x++) cells.add(y * SIZE + x);
    for (const x of columns) for (let y = 0; y < SIZE; y++) cells.add(y * SIZE + x);
    return {rows, columns, cells: [...cells], count: rows.length + columns.length};
  }
  function simulate(board, shape, x, y, color = 1) {
    const next = board.slice();
    for (const [dx, dy] of shape.cells) next[(y + dy) * SIZE + x + dx] = color;
    const clear = lines(next);
    const beforeClear = next.slice();
    for (const i of clear.cells) next[i] = 0;
    return {board: next, beforeClear, ...clear};
  }
  function hasMove(board, tray) {
    return tray.some(piece => {
      const shape = getShape(piece);
      if (!shape) return false;
      for (let y = 0; y <= SIZE - shape.height; y++) {
        for (let x = 0; x <= SIZE - shape.width; x++) if (fits(board, shape, x, y)) return true;
      }
      return false;
    });
  }
  function weighted(items, random) {
    let value = random() * items.reduce((sum, item) => sum + item.shape.weight, 0);
    for (const item of items) { value -= item.shape.weight; if (value < 0) return item; }
    return items[items.length - 1];
  }

  // Construct a legal three-move sequence on a scratch board, then shuffle its
  // pieces. There is always a solution when dealt, but the player must find one.
  // No future move is selected for the player and the real board is untouched.
  function deal(board, random = Math.random) {
    let scratch = board.slice();
    const tray = [];
    for (let i = 0; i < 3; i++) {
      const options = SHAPES.map(shape => ({shape, spots: placements(scratch, shape)})).filter(item => item.spots.length);
      if (!options.length) return [];
      const {shape, spots} = weighted(options, random);
      const spot = spots[Math.floor(random() * spots.length)];
      tray.push({shape: shape.id, color: 1 + Math.floor(random() * 7)});
      scratch = simulate(scratch, shape, spot.x, spot.y).board;
    }
    for (let i = tray.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [tray[i], tray[j]] = [tray[j], tray[i]];
    }
    return tray;
  }

  class Game {
    constructor(random = Math.random) { this.random = random; this.reset(); }
    reset() {
      this.board = emptyBoard();
      this.tray = deal(this.board, this.random);
      this.score = 0;
      this.combo = 0;
      this.misses = 0;
      this.moves = 0;
      this.totalLines = 0;
      this.over = false;
    }
    preview(slot, x, y) {
      const piece = this.tray[slot], shape = getShape(piece);
      if (!fits(this.board, shape, x, y)) return null;
      return simulate(this.board, shape, x, y, piece.color);
    }
    place(slot, x, y) {
      if (this.over) return null;
      const result = this.preview(slot, x, y);
      if (!result) return null;
      const piece = this.tray[slot], shape = getShape(piece);
      if (result.count) { this.combo++; this.misses = 0; }
      else if (++this.misses >= 3) { this.combo = 0; this.misses = 0; }
      const allClear = result.count > 0 && result.board.every(cell => cell === 0);
      const gain = shape.cells.length + 100 * result.count ** 2 * this.combo + (allClear ? 300 : 0);
      this.score += gain;
      this.moves++;
      this.totalLines += result.count;
      this.board = result.board;
      this.tray[slot] = null;
      const refill = this.tray.every(piece => !piece);
      if (refill) this.tray = deal(this.board, this.random);
      this.over = !hasMove(this.board, this.tray);
      return {...result, gain, allClear, refill, piece, x, y, combo: this.combo};
    }
    serialize() {
      return {version: 1, board: this.board.slice(), tray: this.tray.map(p => p && {...p}),
        score: this.score, combo: this.combo, misses: this.misses, moves: this.moves, totalLines: this.totalLines};
    }
    restore(data) {
      const integer = (v, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(v) && v >= min && v <= max;
      if (!data || data.version !== 1 || !Array.isArray(data.board) || data.board.length !== 64 ||
          !data.board.every(v => integer(v, 0, 7)) || !Array.isArray(data.tray) || data.tray.length !== 3 ||
          !data.tray.every(p => p === null || (getShape(p) && integer(p.color, 1, 7))) ||
          !['score', 'combo', 'moves', 'totalLines'].every(k => integer(data[k])) ||
          !integer(data.misses, 0, 2) || data.combo > data.moves || data.totalLines > data.moves * 16 ||
          lines(data.board).count || !hasMove(data.board, data.tray)) return false;
      this.board = data.board.slice();
      this.tray = data.tray.map(p => p && {shape: p.shape, color: p.color});
      for (const k of ['score', 'combo', 'misses', 'moves', 'totalLines']) this[k] = data[k];
      this.over = false;
      return true;
    }
  }
  const api = {SIZE, SHAPES, Game, emptyBoard, getShape, fits, placements, lines, simulate, hasMove, deal};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ByggaEngine = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
