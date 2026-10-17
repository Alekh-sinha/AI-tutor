const P: Record<string, string> = {
  home: "M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M9 13h6 M9 17h6",
  video: "M3 6h12v12H3z M15 10l6-3v10l-6-3",
  layout: "M3 3h7v9H3z M14 3h7v5h-7z M14 12h7v9h-7z M3 16h7v5H3z",
  bell: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9 M10 21a2 2 0 0 0 4 0",
  play: "M6 4l14 8-14 8z",
  pause: "M6 4h4v16H6z M14 4h4v16h-4z",
  upload: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  mic: "M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z M19 11a7 7 0 0 1-14 0 M12 18v4",
  edit: "M12 20h9 M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  check: "M20 6L9 17l-5-5",
  send: "M22 2L11 13 M22 2l-7 20-4-9-9-4z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.3-4.3",
  more: "M12 5h.01 M12 12h.01 M12 19h.01",
  chev: "M6 9l6 6 6-6",
  x: "M18 6L6 18 M6 6l12 12",
  cam: "M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z",
  msg: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  undo: "M3 7v6h6 M21 17a9 9 0 0 0-15-6.7L3 13",
  users: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M23 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8",
  back: "M19 12H5 M11 18l-6-6 6-6",
  alert: "M12 9v4 M12 17h.01 M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9",
  coin: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v10 M9.5 9.5c0-1 1-1.7 2.5-1.7s2.5.7 2.5 1.7-1 1.5-2.5 1.8-2.5.8-2.5 1.8 1 1.7 2.5 1.7 2.5-.7 2.5-1.7",
};

export function Icon({ n, sm = false }: { n: keyof typeof P | string; sm?: boolean }) {
  return (
    <svg className={`i${sm ? " sm" : ""}`} viewBox="0 0 24 24" aria-hidden>
      <path d={P[n] ?? ""} />
    </svg>
  );
}
