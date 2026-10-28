/**
 * A small "(i)" affordance that explains a term.
 *
 * Works on hover for pointer users and on click/tap + focus for touch and
 * keyboard users, so the explanation is never hover-only (which would be
 * unreachable on a phone). Rendered as a real <button>.
 *
 * The bubble is `position: fixed` and positioned from the button's rect, so it
 * is never clipped by an ancestor with `overflow: hidden` (every .fet-card is).
 */
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Info } from 'lucide-react';

export default function InfoTip({ text, label = 'More information', width = 240 }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, placement: 'top' });
  const wrapRef = useRef(null);
  const btnRef = useRef(null);
  const tipRef = useRef(null);
  const tipId = useId();

  useLayoutEffect(() => {
    if (!open || !btnRef.current) return;
    const place = () => {
      const r = btnRef.current.getBoundingClientRect();
      const tipH = tipRef.current?.offsetHeight || 44;
      const gap = 10;
      const above = r.top - gap - tipH >= 8;
      const placement = above ? 'top' : 'bottom';
      const top = above ? r.top - gap - tipH : r.bottom + gap;
      const half = width / 2;
      const left = Math.min(
        Math.max(r.left + r.width / 2, half + 8),
        window.innerWidth - half - 8,
      );
      setPos({ top, left, placement });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, width]);

  useEffect(() => {
    if (!open) return undefined;
    const onDocDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', onDocDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDocDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span className="ui-infotip-wrap" ref={wrapRef}>
      <button
        ref={btnRef}
        type="button"
        className="ui-infotip-btn"
        aria-label={label}
        aria-describedby={open ? tipId : undefined}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <Info size={13} />
      </button>
      {open ? (
        <span
          ref={tipRef}
          role="tooltip"
          id={tipId}
          className="ui-infotip"
          data-placement={pos.placement}
          style={{ top: pos.top, left: pos.left, width }}
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}
