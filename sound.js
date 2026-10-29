(function (root) {
  'use strict';
  // Original procedural effects: felted marimba attacks, a soft low body and
  // bright glass harmonics. Everything is synthesized locally, including reverb.
  class Sound {
    constructor(context = null) {
      this.context = context;
      this.enabled = true;
      this.master = null;
      this.lastTick = 0;
      if (context) this.build();
    }
    build() {
      const c = this.context;
      this.master = c.createGain();
      this.master.gain.value = this.enabled ? 0.55 : 0;
      const limiter = c.createDynamicsCompressor();
      limiter.threshold.value = -10;
      limiter.knee.value = 12;
      limiter.ratio.value = 5;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.18;
      this.master.connect(limiter).connect(c.destination);
      const convolver = c.createConvolver();
      const impulse = c.createBuffer(2, Math.floor(c.sampleRate * 0.52), c.sampleRate);
      let seed = 8191;
      for (let channel = 0; channel < 2; channel++) {
        const data = impulse.getChannelData(channel);
        for (let i = 0; i < data.length; i++) {
          seed = (Math.imul(seed, 1664525) + 1013904223) | 0;
          data[i] = (seed / 2147483648) * Math.pow(1 - i / data.length, 3) * 0.5;
        }
      }
      convolver.buffer = impulse;
      this.wet = c.createGain();
      this.wet.gain.value = 0.13;
      this.wet.connect(convolver).connect(this.master);
    }
    unlock() {
      if (!this.enabled) return;
      try {
        if (!this.context) {
          const Audio = root.AudioContext || root.webkitAudioContext;
          if (!Audio) return;
          this.context = new Audio({latencyHint: 'interactive'});
          this.build();
        }
        if (this.context.state === 'suspended' || this.context.state === 'interrupted') this.context.resume().catch(() => {});
      } catch (_) { /* Audio is optional, including on restricted devices. */ }
    }
    setEnabled(enabled) {
      this.enabled = enabled;
      if (this.master) this.master.gain.setTargetAtTime(enabled ? 0.55 : 0, this.context.currentTime, 0.015);
      if (enabled) this.unlock();
    }
    note(frequency, when, duration, volume = 0.2, pan = 0, glass = false) {
      const c = this.context;
      const bus = c.createGain();
      let stereo = null;
      if (c.createStereoPanner) {
        stereo = c.createStereoPanner();
        stereo.pan.value = pan;
        bus.connect(stereo).connect(this.master);
      } else bus.connect(this.master);
      bus.connect(this.wet);
      const partials = glass ? [[1, 1], [2, 0.28], [3, 0.1], [4.01, 0.05]] : [[1, 1], [2.76, 0.22], [5.4, 0.06]];
      partials.forEach(([ratio, amplitude], index) => {
        const oscillator = c.createOscillator(), envelope = c.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(frequency * ratio, when);
        const decay = duration / (1 + index * 0.6);
        envelope.gain.setValueAtTime(0, when);
        envelope.gain.linearRampToValueAtTime(volume * amplitude, when + 0.004);
        envelope.gain.exponentialRampToValueAtTime(0.0001, when + decay);
        oscillator.connect(envelope).connect(bus);
        oscillator.start(when);
        oscillator.stop(when + decay + 0.025);
        oscillator.onended = () => {
          oscillator.disconnect(); envelope.disconnect();
          // The fundamental has the longest envelope; release its whole bus
          // after the final partial so a long game cannot accumulate audio nodes.
          if (index === 0) { bus.disconnect(); if (stereo) stereo.disconnect(); }
        };
      });
    }
    play(event, value = 1, when = null) {
      if (!this.enabled || !this.context || !this.master) return;
      const t = when ?? this.context.currentTime + 0.005;
      const note = (f, offset, d, v, p = 0, glass = false) => this.note(f, t + offset, d, v, p, glass);
      if (event === 'pick') note(523.25, 0, 0.09, 0.085);
      if (event === 'tick') {
        if (t - this.lastTick < 0.055) return;
        this.lastTick = t;
        note(784, 0, 0.035, 0.022);
      }
      if (event === 'place') {
        note(130.81, 0, 0.17, 0.25);
        note(261.63, 0, 0.14, 0.18);
        note(523.25, 0.008, 0.1, 0.05);
      }
      if (event === 'invalid') { note(146.83, 0, 0.1, 0.12); note(138.59, 0.065, 0.1, 0.08); }
      if (event === 'clear' || event === 'allclear') {
        const scale = [0, 2, 4, 7, 9, 12, 14, 16];
        const lift = Math.min(Math.max(value - 1, 0), 5) * 2;
        const count = event === 'allclear' ? 8 : 4 + Math.min(value - 1, 3);
        for (let i = 0; i < count; i++) {
          note(261.63 * 2 ** ((scale[i] + lift) / 12), i * 0.047, 0.38, 0.13, (i / (count - 1) - 0.5) * 0.8, true);
        }
        note(130.81 * 2 ** (lift / 12), 0, 0.38, 0.22);
        [0, 4, 7].forEach((n, i) => note(523.25 * 2 ** ((n + lift) / 12), 0.19, 0.56, 0.055, (i - 1) * 0.35, true));
      }
      if (event === 'start') [261.63, 329.63, 392, 523.25].forEach((f, i) => note(f, i * 0.065, 0.32, 0.1, (i - 1.5) * 0.2));
      if (event === 'over') [392, 329.63, 261.63, 196].forEach((f, i) => note(f, i * 0.13, 0.5, 0.12, 0, true));
    }
    suspend() {
      if (this.context && this.context.state === 'running') this.context.suspend().catch(() => {});
    }
  }
  root.ByggaSound = Sound;
})(globalThis);
