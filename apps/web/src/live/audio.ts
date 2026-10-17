/** Browser audio for the streaming live class: play the teacher's 24 kHz PCM as it arrives (gap-free, instantly stoppable) and stream the microphone as 16 kHz PCM chunks. */

export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private next = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private gain: GainNode | null = null;
  /** Called with true when the teacher's voice starts and false when the queue has played out. */
  onSpeaking: (speaking: boolean) => void = () => {};

  /** Must be called from a user gesture (browsers block audio before the first tap). */
  async unlock(): Promise<void> {
    if (!this.ctx) {
      this.ctx = new AudioContext({ sampleRate: 24000 });
      this.gain = this.ctx.createGain();
      this.gain.connect(this.ctx.destination);
    }
    if (this.ctx.state !== "running") await this.ctx.resume();
  }

  push(bytes: ArrayBuffer): void {
    if (!this.ctx || !this.gain) return;
    const i16 = new Int16Array(bytes.byteLength >> 1);
    new Uint8Array(i16.buffer).set(new Uint8Array(bytes, 0, i16.length * 2));
    const f32 = Float32Array.from(i16, (v) => v / 32768);
    const buf = this.ctx.createBuffer(1, f32.length, 24000);
    buf.copyToChannel(f32, 0);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.gain);
    const now = this.ctx.currentTime;
    if (this.next < now + 0.02) { this.next = now + 0.08; if (this.sources.size === 0) this.onSpeaking(true); }  // small cushion against network jitter
    src.start(this.next);
    this.next += buf.duration;
    this.sources.add(src);
    src.onended = () => { this.sources.delete(src); if (this.sources.size === 0) this.onSpeaking(false); };
  }

  /** True while queued teacher audio is still playing (plus a short tail for the room's echo). The microphone must stay silent meanwhile. */
  busy(tail = 0.6): boolean { return !!this.ctx && this.next + tail > this.ctx.currentTime && this.next > 0; }

  /** Seconds on the audio clock at which everything queued so far has been played; text that arrives now belongs to audio that ends about then. Null before unlock. */
  playedAt(): { end: number; now: number } | null { return this.ctx ? { end: Math.max(this.next, this.ctx.currentTime), now: this.ctx.currentTime } : null; }

  /** A child spoke over the teacher: drop everything that was queued. */
  flush(): void {
    this.sources.forEach((s) => { s.onended = null; try { s.stop(); } catch { /* already stopped */ } });
    this.sources.clear();
    this.next = 0;
    this.onSpeaking(false);
  }

  close(): void { this.flush(); void this.ctx?.close(); this.ctx = null; }
}

export interface Mic { stop: () => void }

/** Streams the microphone as 16 kHz mono 16-bit PCM; `onChunk` gets ~0.1 s pieces. Echo cancellation is requested because the teacher's voice plays from the same device. */
export async function startMicStream(onChunk: (pcm: ArrayBuffer) => void): Promise<Mic> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const ctx = new AudioContext({ sampleRate: 16000 });
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(2048, 1, 1);
  proc.onaudioprocess = (e) => {
    const f = e.inputBuffer.getChannelData(0);
    const out = new Int16Array(f.length);
    for (let i = 0; i < f.length; i++) out[i] = Math.max(-1, Math.min(1, f[i])) * 0x7fff;
    onChunk(out.buffer);
  };
  src.connect(proc);
  proc.connect(ctx.destination);
  return { stop: () => { proc.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop()); void ctx.close(); } };
}
