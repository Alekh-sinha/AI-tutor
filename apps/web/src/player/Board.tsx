import { AnimatePresence, motion } from "framer-motion";
import DOMPurify from "dompurify";
import katex from "katex";
import "katex/dist/katex.min.css";
import { useState } from "react";
import type { BoardElement, BoardState, ActiveAnim } from "./board";
import { Figure } from "../live/Figure";

/** Size of the SVG's viewBox, used to keep the label overlay aligned with the picture. */
function viewBoxSize(markup: string): [number, number] {
  const m = /viewBox\s*=\s*["']\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)/.exec(markup);
  return m ? [Number(m[1]), Number(m[2])] : [480, 300];
}

const LETTERS = ["क", "ख", "ग", "घ"];

function ChoiceCard({ el, revealed }: { el: Extract<BoardElement, { type: "choice" }>; revealed: boolean }) {
  const [picked, setPicked] = useState<number | null>(null);
  return (
    <div className="choice">
      <p className="choice-q">{el.question}</p>
      {el.options.map((o, i) => {
        const state = revealed
          ? i === el.answer_index ? "right" : i === picked ? "wrong" : ""
          : i === picked ? "picked" : "";
        return (
          <button key={i} className={`opt ${state}`} disabled={revealed} onClick={() => setPicked(i)}>
            <b>{LETTERS[i]}</b> {o} {state === "right" && "✓"}{state === "wrong" && "✗"}
          </button>
        );
      })}
    </div>
  );
}

function Element({ el, highlighted, anim, revealed }: { el: BoardElement; highlighted: boolean; anim?: ActiveAnim; revealed: boolean }) {
  let body;
  switch (el.type) {
    case "note":
      body = <p className={`note note-${el.style ?? "body"}`}>{el.text}</p>;
      break;
    case "image":
      body = (
        <figure>
          <img src={el.src} alt={el.caption ?? ""} />
          {el.caption && <figcaption>{el.caption}</figcaption>}
        </figure>
      );
      break;
    case "figure":
      body = (
        <figure>
          <Figure html={el.html} />
          {el.caption && <figcaption>{el.caption}</figcaption>}
        </figure>
      );
      break;
    case "svg": {
      const [w, h] = viewBoxSize(el.markup);
      body = (
        <figure>
          <div className="svgbox" style={{ aspectRatio: `${w} / ${h}`, width: `min(100%, calc(40vh * ${w / h}))` }}>
            <div
              className="svg"
              dangerouslySetInnerHTML={{
                __html: DOMPurify.sanitize(el.markup, { USE_PROFILES: { svg: true } }),
              }}
            />
            {(el.labels ?? []).map((l, i) => (
              <span
                key={i}
                className="svglabel"
                style={{
                  left: `${l.x}%`,
                  top: `${l.y}%`,
                  fontSize: `${l.size ?? 4.6}cqw`,
                  color: l.color ?? undefined,
                  fontWeight: l.bold ? 700 : 500,
                }}
              >
                {l.text}
              </span>
            ))}
          </div>
          {el.caption && <figcaption>{el.caption}</figcaption>}
        </figure>
      );
      break;
    }
    case "choice":
      body = <ChoiceCard el={el} revealed={revealed} />;
      break;
    case "equation":
      body = (
        <div
          className="equation"
          dangerouslySetInnerHTML={{
            __html: katex.renderToString(el.latex, { throwOnError: false, displayMode: true }),
          }}
        />
      );
      break;
  }
  return (
    <motion.div
      layout
      className={`${highlighted ? "el highlighted" : "el"} el-${el.type}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div key={anim?.since} className={anim ? `fx fx-${anim.effect}` : undefined}>
        {body}
        {anim?.effect === "tick" && <span className="badge badge-tick">✓</span>}
        {anim?.effect === "cross" && <span className="badge badge-cross">✗</span>}
        {anim?.effect === "arrow" && <span className="badge badge-arrow">👇</span>}
      </div>
    </motion.div>
  );
}

export function Board({ state, time }: { state: BoardState; time: number }) {
  return (
    <div className="board">
      <AnimatePresence>
        {state.elements.map((el) => (
          <Element key={el.id} el={el} highlighted={state.highlighted === el.id} anim={state.anims[el.id]} revealed={el.type === "choice" && time >= el.reveal_at} />
        ))}
      </AnimatePresence>
    </div>
  );
}
