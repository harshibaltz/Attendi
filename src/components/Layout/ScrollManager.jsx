import { useEffect, useLayoutEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

// Scroll positions for the app's scroll container, keyed by the history entry
// (location.key) so Back/Forward can restore them.
const positions = new Map();

// The app scrolls inside a dedicated container (the <main class="app-scroll">),
// not the window, so we track that element rather than window.scrollY.
const getScroller = () => {
  if (typeof document === 'undefined') return null;
  return (
    document.querySelector('.app-scroll') ||
    document.scrollingElement ||
    document.documentElement
  );
};

/**
 * Keeps track of the scroll position of the app's scroll container.
 *
 * - Normal navigation (a link click) starts the new screen at the top.
 * - Returning through history (Back/Forward) restores the saved position for
 *   that history entry.
 */
const ScrollManager = () => {
  const location = useLocation();
  const navigationType = useNavigationType();
  const currentKey = useRef(location.key);

  currentKey.current = location.key;

  // Runs after the new route is committed but before the browser paints, so
  // there is no flicker or visible jump.
  useLayoutEffect(() => {
    const target = getScroller();
    if (!target) return;
    if (navigationType === 'POP') {
      const saved = positions.get(location.key);
      if (saved != null) target.scrollTop = saved;
    } else {
      target.scrollTop = 0;
    }
  }, [location.key, navigationType]);

  // Continuously record the container's scroll position for the active history
  // entry. A single listener (re-keyed via the ref) avoids ordering problems
  // when the location changes.
  useEffect(() => {
    const target = getScroller();
    if (!target) return undefined;

    const record = () => {
      positions.set(currentKey.current, target.scrollTop);
    };

    record();
    target.addEventListener('scroll', record, { passive: true });
    return () => target.removeEventListener('scroll', record);
  }, []);

  return null;
};

export default ScrollManager;
