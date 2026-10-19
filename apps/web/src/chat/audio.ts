/** ONE answer player for the whole page: a new answer replaces the one still playing, and closing the chat stops it (each chat panel used to have its own player, so an old answer could play over a new one). */
let current: HTMLAudioElement | null = null;

export function playAnswer(b64: string): void {
  stopAnswer();
  const a = new Audio(`data:audio/mpeg;base64,${b64}`);
  current = a;
  void a.play().catch(() => undefined);
}

export function stopAnswer(): void {
  current?.pause();
  current = null;
}
